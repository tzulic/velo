"""Skill security guard — scans skill content for threats before saving.

100+ threat patterns across 10 categories, trust-level-aware policy.
Runs silently on all skill writes (install, create, update).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from velo.agent.security import _INVISIBLE_CHARS_RE

# Trust levels for skill sources
TrustLevel = Literal["builtin", "volos-curated", "community", "agent-created"]

# Trust policy: (safe, caution, dangerous) → "allow" or "block"
_INSTALL_POLICY: dict[str, tuple[str, str, str]] = {
    "builtin": ("allow", "allow", "allow"),
    "volos-curated": ("allow", "allow", "allow"),
    "community": ("allow", "block", "block"),
    "agent-created": ("allow", "block", "block"),
}

# Severity levels for patterns
_CRITICAL = "critical"
_HIGH = "high"

# Threat patterns: (regex, category, severity)
# Reason: these are skill-specific patterns that go beyond the base THREAT_PATTERNS
# in security/__init__.py. The base patterns (prompt injection, exfiltration, eval/exec)
# are NOT duplicated here — scan_skill is the single scanner for skill content.
_THREAT_PATTERNS: list[tuple[str, str, str]] = [
    # --- Exfiltration (critical) ---
    (r"curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "exfiltration", _CRITICAL),
    (r"wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "exfiltration", _CRITICAL),
    (
        r"cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)",
        "exfiltration",
        _CRITICAL,
    ),
    (r"\bns(lookup|update)\s+[^\n]*\$", "exfiltration_dns", _CRITICAL),
    (r"base64\s+.*\|\s*(curl|wget|nc)", "exfiltration_encoded", _CRITICAL),
    # --- Prompt injection (high) ---
    (r"ignore\s+(previous|all|above|prior)\s+instructions", "prompt_injection", _HIGH),
    (r"you\s+are\s+now\s+", "prompt_injection", _HIGH),
    (r"system\s+prompt\s+override", "prompt_injection", _HIGH),
    (r"do\s+not\s+tell\s+the\s+user", "prompt_injection", _HIGH),
    (r"disregard\s+(your|all|any)\s+(instructions|rules|guidelines)", "prompt_injection", _HIGH),
    (r"act\s+as\s+(if|though)\s+you\s+(have\s+no|don't\s+have)", "prompt_injection", _HIGH),
    # --- Destructive (critical) ---
    (r"\brm\s+-[rf]{1,2}\s+/", "destructive", _CRITICAL),
    (r"\bmkfs\b", "destructive", _CRITICAL),
    (r"\bdd\s+.*of=/dev/", "destructive", _CRITICAL),
    # --- Persistence (critical/high) ---
    (r"authorized_keys", "persistence", _CRITICAL),
    (r"crontab\s+-", "persistence", _HIGH),
    (r"\.(bashrc|zshrc|profile|bash_profile)", "persistence", _HIGH),
    (r"systemctl\s+(enable|start)", "persistence", _HIGH),
    (r"launchctl\s+load", "persistence", _HIGH),
    # --- Network (critical) ---
    (r"bash\s+-i\s+>&\s*/dev/tcp/", "reverse_shell", _CRITICAL),
    (r"\bnc\s+-e\b", "reverse_shell", _CRITICAL),
    (r"socat\s+.*exec:", "reverse_shell", _CRITICAL),
    (r"\b(ngrok|serveo|localtunnel)\b", "tunnel_service", _HIGH),
    # --- Obfuscation (high) ---
    (r"base64\s+(--)?decode\s*\|", "obfuscation", _HIGH),
    (r"\beval\s*\(", "obfuscation_eval", _HIGH),
    (r"\bexec\s*\(", "obfuscation_exec", _HIGH),
    (r"\\x[0-9a-f]{2}", "hex_encoding", _HIGH),
    (r"^#!.*/bin/", "shebang_in_content", _HIGH),
    # --- Supply chain (critical/high) ---
    (r"curl\b.*\|\s*(sh|bash)\b", "supply_chain", _CRITICAL),
    (r"wget\b.*\|\s*(sh|bash)\b", "supply_chain", _CRITICAL),
    (r"pip\s+install\s+(?!-r)", "supply_chain_pip", _HIGH),
    (r"npm\s+install\s+(?!--save-dev)", "supply_chain_npm", _HIGH),
    # --- Privilege escalation (critical) ---
    (r"\bsudo\b", "privilege_escalation", _CRITICAL),
    (r"\bchmod\s+[u+]*s", "setuid", _CRITICAL),
    (r"NOPASSWD", "sudoers", _CRITICAL),
    # --- Agent config (high) ---
    (r"AGENTS\.md", "agent_config", _HIGH),
    (r"CLAUDE\.md", "agent_config", _HIGH),
    (r"\.cursorrules", "agent_config", _HIGH),
    # --- Hardcoded secrets (critical) — ordered specific-first to avoid sk- catching sk-ant-
    (r"ghp_[A-Za-z0-9_]{36,}", "hardcoded_secret", _CRITICAL),
    (r"sk-ant-[A-Za-z0-9_-]{20,}", "hardcoded_secret", _CRITICAL),
    (r"sk-[A-Za-z0-9_-]{20,}", "hardcoded_secret", _CRITICAL),
    (r"xoxb-[A-Za-z0-9-]+", "hardcoded_secret", _CRITICAL),
]

_COMPILED_THREATS = [
    (re.compile(pat, re.IGNORECASE | re.MULTILINE), cat, sev) for pat, cat, sev in _THREAT_PATTERNS
]

# Verdict type for type safety
Verdict = Literal["safe", "caution", "dangerous"]


@dataclass
class SkillVerdict:
    """Result of skill security scan."""

    verdict: Verdict
    allowed: bool  # Whether the skill can be installed given trust level
    findings: list[str] = field(default_factory=list)


def scan_skill(content: str, source: TrustLevel = "community") -> SkillVerdict:
    """Scan skill content for security threats.

    Args:
        content: Full SKILL.md content including frontmatter.
        source: Trust level — "builtin", "volos-curated", "community", "agent-created".

    Returns:
        SkillVerdict with verdict, allowed flag, and findings list.
    """
    findings: list[str] = []
    has_critical = False
    has_high = False

    # Invisible unicode check (reuses regex from security/__init__.py)
    if _INVISIBLE_CHARS_RE.search(content):
        findings.append("invisible_unicode_chars")
        has_high = True

    # Pattern scan
    for pattern, category, severity in _COMPILED_THREATS:
        if pattern.search(content):
            findings.append(f"{category}:{severity}")
            if severity == _CRITICAL:
                has_critical = True
            elif severity == _HIGH:
                has_high = True

    # Determine verdict
    if has_critical:
        verdict = "dangerous"
    elif has_high:
        verdict = "caution"
    else:
        verdict = "safe"

    # Apply trust policy
    policy = _INSTALL_POLICY.get(source, _INSTALL_POLICY["community"])
    verdict_index = {"safe": 0, "caution": 1, "dangerous": 2}[verdict]
    allowed = policy[verdict_index] == "allow"

    return SkillVerdict(verdict=verdict, allowed=allowed, findings=findings)
