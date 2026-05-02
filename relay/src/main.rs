use std::env;
use std::io::{self, Read, Write};
use std::net::{Ipv4Addr, Ipv6Addr, Shutdown, TcpListener, TcpStream};
use std::process;
use std::thread;
use std::time::Duration;

#[derive(Clone)]
enum RelayMode {
    Direct,
    Proxy { upstream: UpstreamProxy },
}

#[derive(Clone)]
enum UpstreamProtocol {
    HttpConnect,
    Socks5,
}

#[derive(Clone)]
struct UpstreamProxy {
    protocol: UpstreamProtocol,
    endpoint: Endpoint,
}

#[derive(Clone)]
struct Endpoint {
    host: String,
    port: u16,
}

struct RelayConfig {
    mode: RelayMode,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("proxy-relay: {error}");
        process::exit(1);
    }
}

fn run() -> io::Result<()> {
    let config = parse_args(env::args().skip(1).collect())?;
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let port = listener.local_addr()?.port();
    println!("RELAY_READY port={port} mode={}", mode_name(&config.mode));
    io::stdout().flush()?;

    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                let mode = config.mode.clone();
                thread::spawn(move || {
                    if let Err(error) = handle_client(stream, mode) {
                        eprintln!("proxy-relay client error: {error}");
                    }
                });
            }
            Err(error) => eprintln!("proxy-relay accept error: {error}"),
        }
    }

    Ok(())
}

fn parse_args(args: Vec<String>) -> io::Result<RelayConfig> {
    let mut mode: Option<String> = None;
    let mut upstream: Option<String> = None;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--mode" => {
                index += 1;
                mode = args.get(index).cloned();
            }
            "--upstream" => {
                index += 1;
                upstream = args.get(index).cloned();
            }
            "--parent-pid" => {
                index += 1;
                let _ = args.get(index);
            }
            other => {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!("unknown argument {other}"),
                ));
            }
        }
        index += 1;
    }

    let relay_mode = match mode.as_deref() {
        Some("direct") => RelayMode::Direct,
        Some("proxy") => {
            let upstream = upstream.ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidInput, "--upstream is required")
            })?;
            RelayMode::Proxy {
                upstream: parse_upstream_proxy(&upstream)?,
            }
        }
        _ => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "--mode must be direct or proxy",
            ))
        }
    };

    Ok(RelayConfig { mode: relay_mode })
}

fn handle_client(mut client: TcpStream, mode: RelayMode) -> io::Result<()> {
    client.set_read_timeout(Some(Duration::from_secs(10)))?;
    client.set_write_timeout(Some(Duration::from_secs(10)))?;
    let request = read_http_head(&mut client)?;
    if request.is_empty() {
        return Ok(());
    }

    match mode {
        RelayMode::Proxy { upstream } => handle_via_upstream(client, request, upstream),
        RelayMode::Direct => handle_direct(client, request),
    }
}

fn handle_via_upstream(
    client: TcpStream,
    request: Vec<u8>,
    upstream: UpstreamProxy,
) -> io::Result<()> {
    match upstream.protocol {
        UpstreamProtocol::HttpConnect => handle_via_http_proxy(client, request, upstream.endpoint),
        UpstreamProtocol::Socks5 => handle_via_socks5_proxy(client, request, upstream.endpoint),
    }
}

fn handle_via_http_proxy(
    mut client: TcpStream,
    request: Vec<u8>,
    upstream: Endpoint,
) -> io::Result<()> {
    let mut upstream_stream = match connect_with_timeout_settings(&upstream) {
        Ok(stream) => stream,
        Err(_) => {
            write_502(&mut client)?;
            return Ok(());
        }
    };
    upstream_stream.set_read_timeout(Some(Duration::from_secs(10)))?;
    upstream_stream.set_write_timeout(Some(Duration::from_secs(10)))?;
    upstream_stream.write_all(&request)?;

    if is_connect_request(&request) {
        let response = read_http_head(&mut upstream_stream)?;
        client.write_all(&response)?;
        if response.starts_with(b"HTTP/1.1 200") || response.starts_with(b"HTTP/1.0 200") {
            return tunnel(client, upstream_stream);
        }
        return Ok(());
    }

    copy_response(upstream_stream, client)
}

fn handle_via_socks5_proxy(
    mut client: TcpStream,
    request: Vec<u8>,
    upstream: Endpoint,
) -> io::Result<()> {
    let parsed = ParsedRequest::parse(&request)?;
    let mut upstream_stream = match connect_socks5(&upstream, &parsed.endpoint) {
        Ok(stream) => stream,
        Err(_) => {
            write_502(&mut client)?;
            return Ok(());
        }
    };

    if parsed.method.eq_ignore_ascii_case("CONNECT") {
        client.write_all(b"HTTP/1.1 200 Connection Established\r\n\r\n")?;
        return tunnel(client, upstream_stream);
    }

    upstream_stream.write_all(&parsed.forward_request)?;
    copy_response(upstream_stream, client)
}

fn handle_direct(mut client: TcpStream, request: Vec<u8>) -> io::Result<()> {
    let parsed = ParsedRequest::parse(&request)?;
    let mut target = TcpStream::connect((parsed.endpoint.host.as_str(), parsed.endpoint.port))?;
    target.set_read_timeout(Some(Duration::from_secs(10)))?;
    target.set_write_timeout(Some(Duration::from_secs(10)))?;

    if parsed.method.eq_ignore_ascii_case("CONNECT") {
        client.write_all(b"HTTP/1.1 200 Connection Established\r\n\r\n")?;
        tunnel(client, target)
    } else {
        target.write_all(&parsed.forward_request)?;
        copy_response(target, client)
    }
}

fn connect_with_timeout_settings(endpoint: &Endpoint) -> io::Result<TcpStream> {
    let stream = TcpStream::connect((endpoint.host.as_str(), endpoint.port))?;
    stream.set_read_timeout(Some(Duration::from_secs(10)))?;
    stream.set_write_timeout(Some(Duration::from_secs(10)))?;
    Ok(stream)
}

fn connect_socks5(upstream: &Endpoint, target: &Endpoint) -> io::Result<TcpStream> {
    let mut stream = connect_with_timeout_settings(upstream)?;
    stream.write_all(&[0x05, 0x01, 0x00])?;

    let mut greeting = [0_u8; 2];
    stream.read_exact(&mut greeting)?;
    if greeting != [0x05, 0x00] {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "socks5 upstream refused no-auth method",
        ));
    }

    let mut request = vec![0x05, 0x01, 0x00];
    if let Ok(ip) = target.host.parse::<Ipv4Addr>() {
        request.push(0x01);
        request.extend_from_slice(&ip.octets());
    } else if let Ok(ip) = target.host.parse::<Ipv6Addr>() {
        request.push(0x04);
        request.extend_from_slice(&ip.octets());
    } else {
        let host_bytes = target.host.as_bytes();
        if host_bytes.len() > u8::MAX as usize {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "socks5 target host is too long",
            ));
        }
        request.push(0x03);
        request.push(host_bytes.len() as u8);
        request.extend_from_slice(host_bytes);
    }
    request.extend_from_slice(&target.port.to_be_bytes());
    stream.write_all(&request)?;

    read_socks5_connect_response(&mut stream)?;
    Ok(stream)
}

fn read_socks5_connect_response(stream: &mut TcpStream) -> io::Result<()> {
    let mut head = [0_u8; 4];
    stream.read_exact(&mut head)?;
    if head[0] != 0x05 || head[1] != 0x00 {
        return Err(io::Error::new(
            io::ErrorKind::ConnectionRefused,
            "socks5 upstream connect failed",
        ));
    }

    let address_len = match head[3] {
        0x01 => 4,
        0x03 => {
            let mut len = [0_u8; 1];
            stream.read_exact(&mut len)?;
            len[0] as usize
        }
        0x04 => 16,
        _ => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "socks5 upstream returned invalid address type",
            ))
        }
    };
    let mut ignored = vec![0_u8; address_len + 2];
    stream.read_exact(&mut ignored)?;
    Ok(())
}

fn read_http_head(stream: &mut TcpStream) -> io::Result<Vec<u8>> {
    let mut request = Vec::with_capacity(4096);
    let mut buffer = [0_u8; 1];

    while request.len() < 64 * 1024 {
        let count = stream.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        request.extend_from_slice(&buffer[..count]);
        if request.ends_with(b"\r\n\r\n") {
            break;
        }
    }

    Ok(request)
}

fn copy_response(mut source: TcpStream, mut destination: TcpStream) -> io::Result<()> {
    let _ = io::copy(&mut source, &mut destination)?;
    let _ = destination.shutdown(Shutdown::Write);
    Ok(())
}

fn tunnel(client: TcpStream, target: TcpStream) -> io::Result<()> {
    client.set_read_timeout(None)?;
    client.set_write_timeout(None)?;
    target.set_read_timeout(None)?;
    target.set_write_timeout(None)?;

    let mut client_reader = client.try_clone()?;
    let mut client_writer = client;
    let mut target_reader = target.try_clone()?;
    let mut target_writer = target;

    let upload = thread::spawn(move || {
        let _ = io::copy(&mut client_reader, &mut target_writer);
        let _ = target_writer.shutdown(Shutdown::Write);
    });
    let _ = io::copy(&mut target_reader, &mut client_writer);
    let _ = client_writer.shutdown(Shutdown::Write);
    let _ = upload.join();
    Ok(())
}

fn write_502(stream: &mut TcpStream) -> io::Result<()> {
    stream.write_all(
        b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 20\r\nConnection: close\r\n\r\nupstream unavailable",
    )
}

fn is_connect_request(request: &[u8]) -> bool {
    request
        .get(..8)
        .map(|prefix| prefix.eq_ignore_ascii_case(b"CONNECT "))
        .unwrap_or(false)
}

fn mode_name(mode: &RelayMode) -> &'static str {
    match mode {
        RelayMode::Direct => "direct",
        RelayMode::Proxy { .. } => "proxy",
    }
}

struct ParsedRequest {
    method: String,
    endpoint: Endpoint,
    forward_request: Vec<u8>,
}

impl ParsedRequest {
    fn parse(request: &[u8]) -> io::Result<Self> {
        let text = String::from_utf8_lossy(request);
        let mut lines = text.split("\r\n");
        let request_line = lines
            .next()
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "missing request line"))?;
        let mut parts = request_line.split_whitespace();
        let method = parts
            .next()
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "missing method"))?;
        let target = parts
            .next()
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "missing target"))?;
        let version = parts.next().unwrap_or("HTTP/1.1");

        let (endpoint, origin_target) = if method.eq_ignore_ascii_case("CONNECT") {
            (parse_host_port(target, 443)?, target.to_string())
        } else if target.starts_with("http://") {
            parse_absolute_http_target(target)?
        } else {
            (parse_host_header(&text)?, target.to_string())
        };

        let mut forward_request = Vec::new();
        write!(
            forward_request,
            "{} {} {}\r\n",
            method, origin_target, version
        )
        .unwrap();

        if let Some(header_start) = request.windows(2).position(|window| window == b"\r\n") {
            forward_request.extend_from_slice(&request[header_start + 2..]);
        }

        Ok(Self {
            method: method.to_string(),
            endpoint,
            forward_request,
        })
    }
}

fn parse_absolute_http_target(target: &str) -> io::Result<(Endpoint, String)> {
    let without_scheme = target.strip_prefix("http://").ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidData, "only http URLs are supported")
    })?;
    let (authority, path) = match without_scheme.split_once('/') {
        Some((authority, path)) => (authority, format!("/{path}")),
        None => (without_scheme, "/".to_string()),
    };
    Ok((parse_host_port(authority, 80)?, path))
}

fn parse_upstream_proxy(url: &str) -> io::Result<UpstreamProxy> {
    if let Some(without_scheme) = url.strip_prefix("http://") {
        return Ok(UpstreamProxy {
            protocol: UpstreamProtocol::HttpConnect,
            endpoint: parse_host_port(without_scheme, 80)?,
        });
    }
    if let Some(without_scheme) = url.strip_prefix("https://") {
        return Ok(UpstreamProxy {
            protocol: UpstreamProtocol::HttpConnect,
            endpoint: parse_host_port(without_scheme, 443)?,
        });
    }
    if let Some(without_scheme) = url.strip_prefix("socks5://") {
        return Ok(UpstreamProxy {
            protocol: UpstreamProtocol::Socks5,
            endpoint: parse_host_port(without_scheme, 1080)?,
        });
    }
    Err(io::Error::new(
        io::ErrorKind::InvalidInput,
        "upstream must use http://host:port, https://host:port, or socks5://host:port",
    ))
}

fn parse_host_header(request: &str) -> io::Result<Endpoint> {
    for line in request.split("\r\n") {
        if let Some(value) = line.strip_prefix("Host:") {
            return parse_host_port(value.trim(), 80);
        }
        if let Some(value) = line.strip_prefix("host:") {
            return parse_host_port(value.trim(), 80);
        }
    }
    Err(io::Error::new(
        io::ErrorKind::InvalidData,
        "missing Host header",
    ))
}

fn parse_host_port(value: &str, default_port: u16) -> io::Result<Endpoint> {
    let without_path = value.split('/').next().unwrap_or(value);
    let (host, port) = match without_path.rsplit_once(':') {
        Some((host, port_text)) => {
            let port = port_text
                .parse::<u16>()
                .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "invalid endpoint port"))?;
            (host, port)
        }
        None => (without_path, default_port),
    };

    if host.trim().is_empty() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "endpoint host is empty",
        ));
    }

    Ok(Endpoint {
        host: host.to_string(),
        port,
    })
}
