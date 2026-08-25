---
name: scrub
description: Secret & PII Scrubber. Activate any time the user says "scrub", "sanitize", "redact", "safe to share", "remove secrets", "clean up before sending", or "anonymize" — or whenever they are about to share config files, code, logs, or scripts with an external party (GitHub, forums, vendors, another AI, etc.). Also activate proactively if you observe secrets while reading files.
---

# Secret & PII Scrubber — Claude Code Instructions

Removes secrets, credentials, and PII from any config file, code, log, or document before it is shared externally. Preserves structure and context for troubleshooting.

---

## Supported Formats

YAML, JSON, .env, TOML, INI, HCL/Terraform, shell scripts, Docker Compose, Kubernetes manifests, Ansible, plain text / logs. For unlisted formats apply the same rules using pattern matching — secrets look the same regardless of format.

---

## Priority 1 — Always Redact (No Exceptions)

### By Key Name

Redact the **value** of any field whose key contains:

```
password, passwd, pwd, pass
secret, secret_key, client_secret
token, access_token, refresh_token, id_token, bearer
api_key, apikey, api_secret, api_token, apiKey
auth, authorization, auth_key, auth_token
private_key, signing_key, encryption_key, hmac_key, master_key
credential, credentials
session, session_key, session_token, cookie, csrf_token
webhook, webhook_url, webhook_secret
psk, pre_shared_key, preshared_key
repo_password, repository_password, restic_password
influxdb_token, influx_token, grafana_api_key
cf_api_token, cloudflare_api_key, cloudflare_api_token
jwt_secret, storage_encryption_key
smtp_password, ldap_password, bind_password
```

Use typed placeholders — **never** `XXX` or `***`:

```yaml
password: REDACTED_PASSWORD
api_key: REDACTED_API_KEY
token: REDACTED_TOKEN
webhook_url: REDACTED_WEBHOOK_URL
private_key: REDACTED_PRIVATE_KEY
```

### By Pattern (regardless of key name)

| Pattern | Placeholder |
|---------|-------------|
| `eyJ...` three-part JWT | `REDACTED_JWT` |
| `AKIA[0-9A-Z]{16}` (AWS Access Key ID) | `REDACTED_AWS_ACCESS_KEY_ID` |
| 40-char base64 following AWS key | `REDACTED_AWS_SECRET_ACCESS_KEY` |
| `sk_live_...` | `REDACTED_STRIPE_SECRET_KEY` |
| `sk_test_...` | `REDACTED_STRIPE_TEST_KEY` |
| `ghp_...` (GitHub PAT) | `REDACTED_GITHUB_TOKEN` |
| `gho_...` (GitHub OAuth) | `REDACTED_GITHUB_OAUTH_TOKEN` |
| `xoxb-...` (Slack bot token) | `REDACTED_SLACK_BOT_TOKEN` |
| `xoxp-...` (Slack user token) | `REDACTED_SLACK_USER_TOKEN` |
| `AIza[0-9A-Za-z-_]{35}` (GCP/Firebase) | `REDACTED_GCP_API_KEY` |
| `-----BEGIN ... PRIVATE KEY-----` block | `REDACTED_PRIVATE_KEY_BLOCK` |
| `-----BEGIN CERTIFICATE-----` block | `REDACTED_CERTIFICATE_BLOCK` |
| `SG.[A-Za-z0-9_-]{22}.[A-Za-z0-9_-]{43}` (SendGrid) | `REDACTED_SENDGRID_API_KEY` |
| `AC[0-9a-f]{32}` (Twilio Account SID) | `REDACTED_TWILIO_ACCOUNT_SID` |
| WireGuard PrivateKey / PresharedKey (44-char base64 ending `=`) | `REDACTED_WIREGUARD_PRIVATE_KEY` / `REDACTED_WIREGUARD_PRESHARED_KEY` |
| `claim-[A-Za-z0-9_-]{20,}` (Plex claim token) | `REDACTED_PLEX_CLAIM_TOKEN` |
| 32-char lowercase hex in apiKey/api_key/X-Api-Key (*arr stack) | `REDACTED_ARR_API_KEY` |
| `[0x[0-9A-Fa-f]{2}(, )?]+` 16-element hex array (Zigbee2MQTT network key) | `REDACTED_ZIGBEE_NETWORK_KEY` |
| Mullvad account number (16 digits) | `REDACTED_MULLVAD_ACCOUNT` |
| CF_API_TOKEN / CLOUDFLARE_API_KEY / CLOUDFLARE_API_TOKEN | `REDACTED_CLOUDFLARE_API_TOKEN` |
| Long random string (>20 chars hex/base64) in a secret-named field | `REDACTED_SECRET_VALUE` |

### URLs with Embedded Credentials

Strip `user:password@` from all URLs. Preserve protocol, host, port, path.

```yaml
# Before
path: rtsp://admin:myPassword@192.168.1.181:554/stream1
db_url: postgresql://app_user:s3cr3t@db.internal:5432/mydb

# After
path: rtsp://admin:REDACTED_PASSWORD@192.168.1.181:554/stream1
db_url: postgresql://app_user:REDACTED_PASSWORD@db.internal:5432/mydb
```

Non-sensitive usernames like `admin`, `frigate`, or service labels may be preserved.

### Query String Secrets

Redact values for these query parameters in any URL:

```
token, key, api_key, apikey, secret, signature, sig,
auth, code, password, access_token, refresh_token,
client_secret, webhook_token, hash
```

Non-secret params (`user`, `page`, `format`, `lang`) are preserved.

### Multiline Blocks

Collapse entire private key / certificate blocks to a single placeholder line:

```yaml
private_key: |
  REDACTED_PRIVATE_KEY_BLOCK
tls_cert: |
  REDACTED_CERTIFICATE_BLOCK
```

### Environment Variables

Redact in all common styles:

```bash
# .env
MQTT_PASSWORD=REDACTED_PASSWORD
STRIPE_SECRET_KEY=REDACTED_STRIPE_SECRET_KEY

# YAML map
environment:
  API_KEY: REDACTED_API_KEY

# YAML list
environment:
  - DATABASE_URL=postgresql://user:REDACTED_PASSWORD@host/db
```

### Database / Connection Strings

```
mongodb://user:REDACTED_PASSWORD@host:27017/db
mysql://user:REDACTED_PASSWORD@host/db
redis://:REDACTED_PASSWORD@host:6379
amqp://user:REDACTED_PASSWORD@rabbitmq:5672/vhost
```

### Cloud Service Account Files (JSON)

Redact `private_key_id`, `private_key`, `client_id` in GCP/AWS/Azure credential JSON.

---

## Priority 2 — PII (Always Redact by Default)

| PII Type | Placeholder |
|----------|-------------|
| Social Security Number | `REDACTED_SSN` |
| Credit/debit card number | `REDACTED_CARD_NUMBER` |
| Bank account / routing number | `REDACTED_BANK_ACCOUNT` |
| Passport number | `REDACTED_PASSPORT_NUMBER` |
| Driver's license number | `REDACTED_DL_NUMBER` |
| National ID / tax ID / EIN | `REDACTED_NATIONAL_ID` |
| Date of birth | `REDACTED_DATE_OF_BIRTH` |
| Full name (in user/contact records) | `REDACTED_FULL_NAME` |
| Email address | `REDACTED_EMAIL` |
| Phone number | `REDACTED_PHONE_NUMBER` |
| Home / mailing address | `REDACTED_ADDRESS` |
| GPS coordinates (personal context) | `REDACTED_COORDINATES` |
| Medical record / health plan number | `REDACTED_MEDICAL_ID` |
| Biometric identifier | `REDACTED_BIOMETRIC_ID` |

**Exception:** Frigate camera names, service labels, and non-personal config keys (e.g., `camera_name: backyard`) are structural identifiers — preserve them.

---

## Priority 3 — Redact Only When User Requests "Public Forum Safe" or "Maximum Anonymization"

Use stable numbered placeholders so relationships stay legible:

| Item | Placeholder |
|------|-------------|
| Internal IP addresses | `CAMERA_1_IP`, `DB_SERVER_IP`, etc. |
| Public IP addresses | `REDACTED_PUBLIC_IP` |
| Internal hostnames | `INTERNAL_HOST_1` |
| Domain names (if revealing) | `REDACTED_DOMAIN` |
| MAC addresses | `REDACTED_MAC_ADDRESS` |
| Serial numbers / device IDs | `REDACTED_SERIAL` |
| Zigbee device IEEE addresses (`0x` + 16 hex chars) | `REDACTED_ZIGBEE_IEEE` |
| Z-Wave node IDs (in automation context) | `REDACTED_ZWAVE_NODE_ID` |
| UPS serial numbers (NUT configs) | `REDACTED_UPS_SERIAL` |
| Cloudflare Zone ID | `REDACTED_CF_ZONE_ID` |

---

## Format-Specific Rules

### Home Assistant & Frigate

Always check:
- MQTT passwords and usernames
- RTSP camera URLs (embedded `username:password`)
- ONVIF username and password
- Frigate Plus API keys / model tokens
- HA long-lived access tokens
- Webhook URLs (notify, Nabu Casa, etc.)
- Cloudflared tunnel tokens
- ESPHome API encryption keys
- Add-on ingress auth tokens

### Unraid / Homelab Stack

**WireGuard** — redact `PrivateKey` and `PresharedKey` in `[Interface]` / `[Peer]` blocks:

```ini
[Interface]
PrivateKey = REDACTED_WIREGUARD_PRIVATE_KEY

[Peer]
PublicKey = <public key is safe>
PresharedKey = REDACTED_WIREGUARD_PRESHARED_KEY
```

**wpa_supplicant / NetworkManager** — redact `psk=` values:

```
network={
    ssid="MyHomeNetwork"
    psk=REDACTED_PSK
}
```

***arr stack** (Sonarr, Radarr, Prowlarr, Lidarr, etc.) — redact 32-char hex API keys:

```yaml
ApiKey: REDACTED_ARR_API_KEY
```

**Plex** — redact claim tokens and auth tokens:

```yaml
environment:
  PLEX_CLAIM: REDACTED_PLEX_CLAIM_TOKEN
  PLEX_TOKEN: REDACTED_TOKEN
```

**Rclone** (`rclone.conf`) — redact cloud storage credentials:

```ini
[b2-backup]
account = REDACTED_B2_ACCOUNT_ID
key = REDACTED_B2_APP_KEY
```

**Zigbee2MQTT** — redact the network key hex array:

```yaml
advanced:
  network_key: REDACTED_ZIGBEE_NETWORK_KEY
```

**Authelia** — redact all secrets in `configuration.yml`:

```yaml
jwt_secret: REDACTED_JWT_SECRET
session:
  secret: REDACTED_SECRET
storage:
  encryption_key: REDACTED_STORAGE_ENCRYPTION_KEY
notifier:
  smtp:
    password: REDACTED_PASSWORD
```

**InfluxDB / Grafana** — redact tokens and admin passwords:

```yaml
environment:
  DOCKER_INFLUXDB_INIT_PASSWORD: REDACTED_PASSWORD
  DOCKER_INFLUXDB_INIT_ADMIN_TOKEN: REDACTED_INFLUXDB_TOKEN
  GF_SECURITY_ADMIN_PASSWORD: REDACTED_PASSWORD
```

**fstab / SMB mounts** — redact inline passwords:

```
//nas.local/share /mnt/nas cifs username=admin,password=REDACTED_PASSWORD,uid=1000 0 0
```

**Restic / backup tools:**

```yaml
environment:
  RESTIC_PASSWORD: REDACTED_RESTIC_PASSWORD
  B2_ACCOUNT_KEY: REDACTED_B2_APP_KEY
```

**Gluetun / VPN provider credentials:**

```yaml
environment:
  OPENVPN_USER: REDACTED_VPN_USERNAME
  OPENVPN_PASSWORD: REDACTED_VPN_PASSWORD
  WIREGUARD_PRIVATE_KEY: REDACTED_WIREGUARD_PRIVATE_KEY
  WIREGUARD_PRESHARED_KEY: REDACTED_WIREGUARD_PRESHARED_KEY
```

**Unraid registration key** — fully redact `.key` file contents or any keyfile value.

### Docker Compose

Preserve secret file references, redact inline values:

```yaml
# Keep (file reference is not a secret):
secrets:
  mqtt_password:
    file: ./secrets/mqtt_password

# Redact (inline value):
environment:
  MQTT_PASSWORD: REDACTED_PASSWORD
```

### Kubernetes Secrets

Base64-encoded values must be redacted even if they look like gibberish:

```yaml
data:
  password: REDACTED_BASE64_SECRET
  api-key: REDACTED_BASE64_SECRET
```

### Terraform / HCL

```hcl
variable "db_password" {
  default = "REDACTED_PASSWORD"
}

provider "aws" {
  access_key = "REDACTED_AWS_ACCESS_KEY_ID"
  secret_key = "REDACTED_AWS_SECRET_ACCESS_KEY"
}
```

### Shell Scripts / curl

```bash
export API_KEY="REDACTED_API_KEY"
curl -H "Authorization: Bearer REDACTED_TOKEN" https://api.example.com
```

---

## Required Workflow

1. Scan the content for all Priority 1 (secrets/credentials) and Priority 2 (PII) items.
2. Redact using typed placeholders — never generic `XXX` or `***`.
3. Preserve structure, indentation, comments (unless comments contain secrets), and non-sensitive values.
4. Report what categories were scrubbed in a brief summary.
5. Only output the scrubbed version — never echo original secret values anywhere in your response.

---

## Validation Checklist

Before returning scrubbed content, verify:

- [ ] No passwords, tokens, API keys, or private keys remain
- [ ] No `username:password@` patterns with real passwords in URLs
- [ ] No SSN, credit card, passport, or other PII in labeled fields
- [ ] No JWT (`eyJ...`) values remain
- [ ] No cloud provider key patterns (`AKIA...`, `AIza...`, `ghp_...`) remain
- [ ] No WireGuard PrivateKey or PresharedKey values remain
- [ ] No WiFi PSK values remain
- [ ] No Plex claim tokens (`claim-...`) remain
- [ ] No *arr API keys (32-char hex) remain
- [ ] No Zigbee2MQTT network key hex arrays remain
- [ ] No Rclone / backup tool credentials remain
- [ ] No Authelia secrets (`jwt_secret`, `encryption_key`, `session secret`) remain
- [ ] No VPN credentials (Gluetun env vars, OpenVPN auth) remain
- [ ] Placeholders are typed and obvious (`REDACTED_PASSWORD`, not `XXX`)
- [ ] File structure (YAML/JSON/TOML/HCL/INI) is still valid
- [ ] Comments have been checked and do not leak secrets
- [ ] Summary does not repeat any redacted value

---

## Response Format

```
Scrubbed: <brief list of what was redacted>
Preserved: <brief list of what was kept>
```

Then output the scrubbed file contents.
