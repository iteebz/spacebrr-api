---
description: Generate invoices from CLI
---

# Invoice

## Deps

```bash
brew install pandoc
```

## Generate

```bash
cat <<EOF | pandoc -o ~/invoices/INV-001.pdf
# Invoice INV-001

**Tyson Chan**  
space-os | tyson@spaceos.sh  

---

**Bill To:** Acme Corp  
**Date:** 2026-02-09  
**Due:** 2026-03-09

| Description | Qty | Rate | Amount |
|-------------|-----|------|--------|
| Consulting  | 10  | 150  | 1500   |

---

**Total: \$1500**

*Payment: BSB 062-128 / ACC 1049 1707*
EOF
```

## Verify

```bash
pdfinfo ~/invoices/INV-001.pdf
```

## Anti-patterns

- Storing financial data in space (use accounting software)
- Complex tax logic in markdown (calculate externally)
- Version controlling generated PDFs (regenerate from source)
