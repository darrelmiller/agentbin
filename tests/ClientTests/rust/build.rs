use std::fs;

fn main() {
    // Extract a2a-rs-client version from Cargo.toml so it's always in sync
    let cargo_toml = fs::read_to_string("Cargo.toml").expect("Failed to read Cargo.toml");
    let version = cargo_toml
        .lines()
        .find(|line| line.starts_with("a2a-rs-client"))
        .and_then(|line| {
            let parts: Vec<&str> = line.splitn(2, '=').collect();
            parts.get(1).map(|v| v.trim().trim_matches('"').to_string())
        })
        .unwrap_or_else(|| "unknown".to_string());

    println!("cargo:rustc-env=A2A_SDK_VERSION=a2a-rs-client {version}");
    println!("cargo:rerun-if-changed=Cargo.toml");
}
