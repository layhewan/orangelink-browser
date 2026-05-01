use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::Duration;

struct RelayProcess {
    child: Child,
    port: u16,
}

impl Drop for RelayProcess {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

#[test]
fn relay_binds_loopback_ephemeral_port_and_prints_ready_line() {
    let relay = spawn_relay(&["--mode", "direct", "--parent-pid", "0"]);

    assert!(relay.port > 0);
    assert!(TcpStream::connect(("127.0.0.1", relay.port)).is_ok());
}

#[test]
fn source_does_not_use_windows_global_proxy_apis() {
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    let source = fs::read_to_string(format!("{manifest_dir}/src/main.rs")).unwrap();

    assert!(source.contains("127.0.0.1:0"));
    for forbidden in [
        "InternetSetOption",
        "RegSetValue",
        "HKEY_CURRENT_USER",
        "WinHttpSetDefaultProxyConfiguration",
        "ProxyEnable",
        "ProxyServer",
    ] {
        assert!(
            !source.contains(forbidden),
            "relay source must not mutate global proxy setting: {forbidden}"
        );
    }
}

#[test]
fn proxy_mode_returns_502_when_upstream_is_unavailable() {
    let upstream_port = unused_local_port();
    let relay = spawn_relay(&[
        "--mode",
        "proxy",
        "--upstream",
        &format!("http://127.0.0.1:{upstream_port}"),
        "--parent-pid",
        "0",
    ]);

    let response = send_raw_http(
        relay.port,
        "GET http://127.0.0.1:9/check HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n",
    );

    assert!(
        response.starts_with("HTTP/1.1 502 Bad Gateway"),
        "{response}"
    );
}

#[test]
fn direct_mode_connects_directly_only_when_selected() {
    let target = TcpListener::bind("127.0.0.1:0").unwrap();
    let target_port = target.local_addr().unwrap().port();
    let target_thread = thread::spawn(move || {
        let (mut stream, _) = target.accept().unwrap();
        let mut buffer = [0_u8; 1024];
        let _ = stream.read(&mut buffer).unwrap();
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 7\r\nConnection: close\r\n\r\ndirect!")
            .unwrap();
    });
    let relay = spawn_relay(&["--mode", "direct", "--parent-pid", "0"]);

    let response = send_raw_http(
        relay.port,
        &format!(
            "GET http://127.0.0.1:{target_port}/check HTTP/1.1\r\nHost: 127.0.0.1:{target_port}\r\nConnection: close\r\n\r\n"
        ),
    );

    assert!(response.contains("direct!"), "{response}");
    target_thread.join().unwrap();
}

#[test]
fn proxy_mode_tunnels_connect_after_upstream_200() {
    let upstream = TcpListener::bind("127.0.0.1:0").unwrap();
    let upstream_port = upstream.local_addr().unwrap().port();
    let upstream_thread = thread::spawn(move || {
        let (mut stream, _) = upstream.accept().unwrap();
        let mut request = Vec::new();
        let mut byte = [0_u8; 1];
        while !request.ends_with(b"\r\n\r\n") {
            stream.read_exact(&mut byte).unwrap();
            request.extend_from_slice(&byte);
        }
        assert!(String::from_utf8_lossy(&request).starts_with("CONNECT example.test:443"));
        stream
            .write_all(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            .unwrap();

        let mut payload = [0_u8; 4];
        stream.read_exact(&mut payload).unwrap();
        assert_eq!(&payload, b"ping");
        stream.write_all(b"pong").unwrap();
    });
    let relay = spawn_relay(&[
        "--mode",
        "proxy",
        "--upstream",
        &format!("http://127.0.0.1:{upstream_port}"),
        "--parent-pid",
        "0",
    ]);
    let mut client = TcpStream::connect(("127.0.0.1", relay.port)).unwrap();
    client
        .set_read_timeout(Some(Duration::from_secs(3)))
        .unwrap();
    client
        .write_all(b"CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443\r\n\r\n")
        .unwrap();

    let response = read_http_head_from_stream(&mut client);
    assert!(response.starts_with("HTTP/1.1 200 Connection Established"));

    client.write_all(b"ping").unwrap();
    let mut echoed = [0_u8; 4];
    client.read_exact(&mut echoed).unwrap();
    assert_eq!(&echoed, b"pong");
    upstream_thread.join().unwrap();
}

#[test]
fn proxy_mode_treats_https_upstream_as_http_connect_proxy() {
    let upstream = TcpListener::bind("127.0.0.1:0").unwrap();
    let upstream_port = upstream.local_addr().unwrap().port();
    let upstream_thread = thread::spawn(move || {
        let (mut stream, _) = upstream.accept().unwrap();
        let mut request = Vec::new();
        let mut byte = [0_u8; 1];
        while !request.ends_with(b"\r\n\r\n") {
            stream.read_exact(&mut byte).unwrap();
            request.extend_from_slice(&byte);
        }
        assert!(String::from_utf8_lossy(&request).starts_with("CONNECT example.test:443"));
        stream
            .write_all(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            .unwrap();

        let mut payload = [0_u8; 4];
        stream.read_exact(&mut payload).unwrap();
        assert_eq!(&payload, b"ping");
        stream.write_all(b"pong").unwrap();
    });
    let relay = spawn_relay(&[
        "--mode",
        "proxy",
        "--upstream",
        &format!("https://127.0.0.1:{upstream_port}"),
        "--parent-pid",
        "0",
    ]);
    let mut client = TcpStream::connect(("127.0.0.1", relay.port)).unwrap();
    client
        .set_read_timeout(Some(Duration::from_secs(3)))
        .unwrap();
    client
        .write_all(b"CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443\r\n\r\n")
        .unwrap();

    let response = read_http_head_from_stream(&mut client);
    assert!(response.starts_with("HTTP/1.1 200 Connection Established"));

    client.write_all(b"ping").unwrap();
    let mut echoed = [0_u8; 4];
    client.read_exact(&mut echoed).unwrap();
    assert_eq!(&echoed, b"pong");
    upstream_thread.join().unwrap();
}

#[test]
fn proxy_mode_tunnels_connect_through_socks5_upstream() {
    let upstream = TcpListener::bind("127.0.0.1:0").unwrap();
    let upstream_port = upstream.local_addr().unwrap().port();
    let upstream_thread = thread::spawn(move || {
        let (mut stream, _) = upstream.accept().unwrap();
        let mut greeting = [0_u8; 3];
        stream.read_exact(&mut greeting).unwrap();
        assert_eq!(greeting, [0x05, 0x01, 0x00]);
        stream.write_all(&[0x05, 0x00]).unwrap();

        let mut head = [0_u8; 5];
        stream.read_exact(&mut head).unwrap();
        assert_eq!(&head[..4], &[0x05, 0x01, 0x00, 0x03]);
        let domain_len = head[4] as usize;
        let mut domain = vec![0_u8; domain_len];
        stream.read_exact(&mut domain).unwrap();
        let mut port = [0_u8; 2];
        stream.read_exact(&mut port).unwrap();
        assert_eq!(String::from_utf8(domain).unwrap(), "example.test");
        assert_eq!(u16::from_be_bytes(port), 443);
        stream
            .write_all(&[0x05, 0x00, 0x00, 0x01, 0, 0, 0, 0, 0, 0])
            .unwrap();

        let mut payload = [0_u8; 4];
        stream.read_exact(&mut payload).unwrap();
        assert_eq!(&payload, b"ping");
        stream.write_all(b"pong").unwrap();
    });
    let relay = spawn_relay(&[
        "--mode",
        "proxy",
        "--upstream",
        &format!("socks5://127.0.0.1:{upstream_port}"),
        "--parent-pid",
        "0",
    ]);
    let mut client = TcpStream::connect(("127.0.0.1", relay.port)).unwrap();
    client
        .set_read_timeout(Some(Duration::from_secs(3)))
        .unwrap();
    client
        .write_all(b"CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443\r\n\r\n")
        .unwrap();

    let response = read_http_head_from_stream(&mut client);
    assert!(response.starts_with("HTTP/1.1 200 Connection Established"));

    client.write_all(b"ping").unwrap();
    let mut echoed = [0_u8; 4];
    client.read_exact(&mut echoed).unwrap();
    assert_eq!(&echoed, b"pong");
    upstream_thread.join().unwrap();
}

#[test]
fn proxy_mode_keeps_connect_tunnel_open_after_idle_period() {
    let upstream = TcpListener::bind("127.0.0.1:0").unwrap();
    let upstream_port = upstream.local_addr().unwrap().port();
    let upstream_thread = thread::spawn(move || {
        let (mut stream, _) = upstream.accept().unwrap();
        let mut request = Vec::new();
        let mut byte = [0_u8; 1];
        while !request.ends_with(b"\r\n\r\n") {
            stream.read_exact(&mut byte).unwrap();
            request.extend_from_slice(&byte);
        }
        stream
            .write_all(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            .unwrap();

        let mut payload = [0_u8; 4];
        stream.read_exact(&mut payload).unwrap();
        assert_eq!(&payload, b"ping");
        stream.write_all(b"pong").unwrap();
    });
    let relay = spawn_relay(&[
        "--mode",
        "proxy",
        "--upstream",
        &format!("http://127.0.0.1:{upstream_port}"),
        "--parent-pid",
        "0",
    ]);
    let mut client = TcpStream::connect(("127.0.0.1", relay.port)).unwrap();
    client
        .set_read_timeout(Some(Duration::from_secs(3)))
        .unwrap();
    client
        .write_all(b"CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443\r\n\r\n")
        .unwrap();
    let response = read_http_head_from_stream(&mut client);
    assert!(response.starts_with("HTTP/1.1 200 Connection Established"));

    thread::sleep(Duration::from_secs(11));

    client.write_all(b"ping").unwrap();
    let mut echoed = [0_u8; 4];
    client.read_exact(&mut echoed).unwrap();
    assert_eq!(&echoed, b"pong");
    upstream_thread.join().unwrap();
}

fn spawn_relay(args: &[&str]) -> RelayProcess {
    let mut child = Command::new(env!("CARGO_BIN_EXE_proxy-relay"))
        .args(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();

    let stdout = child.stdout.take().unwrap();
    let mut reader = BufReader::new(stdout);
    let mut ready_line = String::new();
    reader.read_line(&mut ready_line).unwrap();

    let port = ready_line
        .split_whitespace()
        .find_map(|part| part.strip_prefix("port="))
        .and_then(|value| value.parse::<u16>().ok())
        .unwrap_or_else(|| panic!("relay did not print ready port: {ready_line:?}"));

    RelayProcess { child, port }
}

fn send_raw_http(port: u16, request: &str) -> String {
    let mut stream = TcpStream::connect(("127.0.0.1", port)).unwrap();
    stream
        .set_read_timeout(Some(Duration::from_secs(3)))
        .unwrap();
    stream.write_all(request.as_bytes()).unwrap();
    stream.shutdown(std::net::Shutdown::Write).unwrap();

    let mut response = String::new();
    stream.read_to_string(&mut response).unwrap();
    response
}

fn read_http_head_from_stream(stream: &mut TcpStream) -> String {
    let mut response = Vec::new();
    let mut byte = [0_u8; 1];
    while !response.ends_with(b"\r\n\r\n") {
        stream.read_exact(&mut byte).unwrap();
        response.extend_from_slice(&byte);
    }
    String::from_utf8(response).unwrap()
}

fn unused_local_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    listener.local_addr().unwrap().port()
}
