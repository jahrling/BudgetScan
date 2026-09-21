# BudgetScan — Security & Privacy

Rules for protecting financial data in a public repo where an LLM assistant
(Claude) is part of the development workflow.

## Core principle

Claude must never read raw financial data directly. Financial data — QIF/QFX
exports, database contents, receipt images, brokerage statements — stays on the
local machine and is processed by scripts. Claude sees only redacted or
aggregated output.

## What counts as sensitive

- Real account names, numbers, and suffixes (e.g. `XX1234`, `...0882`)
- Employer names, beneficiary names, institution names tied to specific accounts
- Transaction amounts, dates, merchants, or memo text from real accounts
- Credit card product names (e.g. "Chase Sapphire Preferred")
- Balances, holdings, lot details, share quantities

## Rules for Claude sessions

### 1. Never read financial data files

Claude must not `cat`, `Read`, or otherwise open:
- QIF, QFX, OFX export files
- SQLite database files (`.db`, `.sqlite`)
- Receipt images or brokerage statement PDFs
- CSV exports from banks or brokerages
- Any file under a `data/` or `data-root/` directory

If Claude needs to understand the structure of these files, use a script that
prints the schema, field names, or a synthetic example — not the real data.

### 2. Scripts must redact before printing

Any script that reads financial data and prints output Claude might see must
redact sensitive values. The pattern from `find_duplicate_accounts.py` is the
model:

```python
def _redact(name: str) -> str:
    """Replace account numbers with XX*** for safe display."""
    s = re.sub(r"(XX|XXXXX)\d{3,}", r"\1***", name)
    s = re.sub(r"\.\.\.\d{3,}", "...***", s)
    s = re.sub(r"\b\d{5,}\b", "***", s)
    return s
```

New scripts must include equivalent redaction before any `print()` that could
surface in Claude's context. Prefer reporting account *types* and *counts*
over names.

### 3. Pre-commit review

Before committing, grep the diff for leaked PII:

```bash
git diff --cached | grep -iE 'XX\d{3,}|XXXXX\d+|\.\.\.\d{3,}'
```

Also check for: employer names, family names, institution-specific account
names, and any string that came from a financial export rather than from code.

### 4. Test fixtures must be synthetic

Never copy real account names, numbers, or transaction data into test files.
Invent names that exercise the same code paths:

- Good: `"Test Brokerage XX1234"`, `"Acme 401k"`
- Bad: a real institution name with a real account suffix

### 5. Findings and documentation

When writing plans, findings, changelogs, or handoff docs, describe accounts
by *type* and *count*, not by real name or number:

- Good: "two HSA accounts, probable duplicates"
- Bad: the real institution name and account number

### 6. Receipt and statement OCR

Receipt images and brokerage PDFs are processed by Ollama locally. Claude may
write or modify the OCR pipeline code, but must not open the source images or
PDFs. If Claude needs to debug OCR results, the pipeline should emit a redacted
summary (field names, confidence scores, extracted field count) rather than the
raw extracted text.

## Incident log

| Date | What happened | Fix |
|------|--------------|-----|
| 2026-09 | `retype_accounts.py` printed real account names; values leaked into handoff docs and test fixture discussions | Added `_redact()` pattern to `find_duplicate_accounts.py`; added QIF PII safeguards to CLAUDE.md |
