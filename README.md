# Hackpot

You've hit the jackpot of cybersecurity tools. Like a honeypot, but instead of getting trapped, you get root.

A curated, category-first index of useful resources for penetration testers and security researchers: tools, courses, documentation, wordlists, payloads, labs, and reading material.

## Categories

| Category | What you'll find |
| --- | --- |
| [01 · Reconnaissance and OSINT](01_Recon_and_OSINT/README.md) | Information gathering, port scanning, subdomain enumeration |
| [02 · Web Application Hacking](02_Web_Application/README.md) | Proxies, scanners, APIs, bruteforcing, flaw-specific tools |
| [03 · Network and Infrastructure](03_Network_and_Infrastructure/README.md) | Active Directory, NAC, and packet analysis |
| [04 · Exploitation and Privilege Escalation](04_Exploitation_and_PrivEsc/README.md) | C2 and exploitation frameworks, Linux/macOS/Windows privesc |
| [05 · Reverse Engineering](05_Reverse_Engineering/README.md) | Disassemblers, decompilers, malware analysis |
| [06 · Cryptography and Cracking](06_Cryptography_and_Cracking/README.md) | Password and hash cracking, steganography |
| [07 · Hardware, IoT and ICS](07_Hardware_IoT_and_ICS/README.md) | Hardware hacking, IoT devices, SCADA, automotive |
| [08 · Cloud and Containers](08_Cloud_and_Containers/README.md) | AWS/Azure/GCP auditing, Docker and Kubernetes |
| [09 · Wordlists and Payloads](09_Wordlists_and_Payloads/README.md) | Dictionaries and reverse-shell payloads |
| [10 · Learning and Resources](10_Learning_and_Resources/README.md) | Blogs, podcasts, cheat sheets, practice labs |
| [11 · AI and Machine Learning](11_AI_and_Machine_Learning/README.md) | Attacking AI systems, AI-assisted offense, and AI coding tools |
| [12 · Mobile](12_Mobile/README.md) | Android, iOS, and cross-platform mobile tooling |
| [13 · Satellite and Space](13_Satellite_and_Space/README.md) | GNSS, satcom, ground systems, and spacecraft security |
| [14 · Wireless and RF](14_Wireless_and_RF/README.md) | Wi-Fi, Bluetooth/BLE, Zigbee, and SDR |
| [15 · Social Engineering](15_Social_Engineering/README.md) | Phishing, vishing/smishing, and pretexting |
| [16 · Red Team Operations](16_Red_Team_Operations/README.md) | AV/EDR evasion, C2 tradecraft, and living off the land |
| [17 · Physical Security](17_Physical_Security/README.md) | Locks, badges, and surveillance countermeasures |

## How the list works

Each category README links its subcategories, and the leaf READMEs hold the actual entries. Every entry follows one format:

- [Name](https://example.com) — what it does and why it matters. `type:tool` `free` `linux`

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full conventions.

## Site and automation

- The browsable site is published from these READMEs to GitHub Pages by CI — never edit the site directly.
- A weekly GitHub Action checks every link with [lychee](https://github.com/lycheeverse/lychee), opens an issue with the broken ones, and refreshes the ★ count and last-update date shown on GitHub-linked entries.

## License

GPL-3.0-only. See [LICENSE](LICENSE).
