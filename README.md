# Hackpot

You've hit the jackpot of cybersecurity tools. Like a honeypot, but instead of getting trapped, you get root.

A curated, category-first index of useful resources for penetration testers and security researchers: tools, courses, documentation, wordlists, payloads, labs, and reading material.

Categories follow the kill chain: recon → initial access → foothold and operations → target surfaces → analysis disciplines → references.

## Categories

| Category | What you'll find |
| --- | --- |
| [01 · Reconnaissance and OSINT](01_Recon_and_OSINT/README.md) | Information gathering, port scanning, subdomain enumeration |
| [02 · Social Engineering](02_Social_Engineering/README.md) | Phishing, vishing/smishing, and pretexting |
| [03 · Physical Security](03_Physical_Security/README.md) | Locks, badges, and surveillance countermeasures |
| [04 · Wireless and RF](04_Wireless_and_RF/README.md) | Wi-Fi, Bluetooth/BLE, Zigbee, and SDR |
| [05 · Exploitation and Privilege Escalation](05_Exploitation_and_PrivEsc/README.md) | C2 and exploitation frameworks, CVE PoC aggregators, Linux/macOS/Windows privesc |
| [06 · Red Team Operations](06_Red_Team_Operations/README.md) | AV/EDR evasion, C2 tradecraft, and living off the land |
| [07 · Network and Infrastructure](07_Network_and_Infrastructure/README.md) | Active Directory, NAC, and packet analysis |
| [08 · Web Application Hacking](08_Web_Application/README.md) | Proxies, scanners, APIs, bruteforcing, flaw-specific tools |
| [09 · Mobile](09_Mobile/README.md) | Android, iOS, and cross-platform mobile tooling |
| [10 · Cloud and Containers](10_Cloud_and_Containers/README.md) | AWS/Azure/GCP auditing, Docker and Kubernetes |
| [11 · Satellite and Space](11_Satellite_and_Space/README.md) | GNSS, satcom, ground systems, and spacecraft security |
| [12 · Hardware, IoT and ICS](12_Hardware_IoT_and_ICS/README.md) | Hardware hacking, IoT devices, SCADA, automotive |
| [13 · Reverse Engineering](13_Reverse_Engineering/README.md) | Disassemblers, decompilers, malware analysis |
| [14 · Cryptography and Cracking](14_Cryptography_and_Cracking/README.md) | Password and hash cracking, steganography |
| [15 · AI and Machine Learning](15_AI_and_Machine_Learning/README.md) | Attacking AI systems, AI-assisted offense, and AI coding tools |
| [16 · Wordlists and Payloads](16_Wordlists_and_Payloads/README.md) | Dictionaries and reverse-shell payloads |
| [17 · Learning and Resources](17_Learning_and_Resources/README.md) | Blogs, podcasts, cheat sheets, practice labs |

## How the list works

Each category README links its subcategories, and the leaf READMEs hold the actual entries. Every entry follows one format:

- [Name](https://example.com) — what it does and why it matters. `type:tool` `free` `linux`

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full conventions.

## Site and automation

- The browsable site is published from these READMEs to GitHub Pages by CI — never edit the site directly.
- A weekly GitHub Action checks every link with [lychee](https://github.com/lycheeverse/lychee), opens an issue with the broken ones, and refreshes the ★ count and last-update date shown on GitHub-linked entries.

## License

GPL-3.0-only. See [LICENSE](LICENSE).
