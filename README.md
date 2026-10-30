# MagicalBoundries clean property briefs + WhatsApp CRM package

## Contents
- `main.py`: FastAPI lead endpoints, append-only SQLite CRM, WhatsApp notifications, dashboard and CSV export. Email notifications are disabled.
- `requirements.txt`: Python dependencies.
- `data/property_catalogue_clean.csv`: master catalogue with direct-contact fields removed.
- `data/project_registry.json`: customer-safe registry, including source notes for uploaded-document projects.
- `data/research_sources_internal.csv` and `data/verified_web_sources.csv`: internal source/verification trackers.
- `brochures/*.pdf`: 220 regenerated customer-facing one-page briefs.

## What changed in this regeneration
Uploaded source material is now reflected in the matching project briefs where readable details were available. For example, the Leafsong brief includes Sector MU, Greater Noida, landscaped greens/open planning, the brochure's AQI monitoring and EV-charging claims, and an explicit certification-verification note. Other uploaded documents have their source-specific details and limitations stated. Historical offer and progress documents are labeled as historical; ambiguous source documents are not silently treated as verified project specifications.

The remaining master-catalogue briefs are explicitly labeled as catalogue-only and not as official brochures. All briefs are generated summaries, not copies of the original multi-page developer PDFs. Direct developer/broker phone numbers, email addresses and contact links are intentionally omitted.

## Deploying safely
1. Back up existing leads before making changes. Do not delete `leads.db` or the Render persistent disk.
2. In the local GitHub Desktop repository, replace the entire `brochures` folder with this package's `brochures` folder. Also replace `data/project_registry.json` and `data/property_catalogue_clean.csv` with the package versions; keep internal source trackers private if desired. Keep `main.py` and `requirements.txt` aligned with the same package.
3. Review changes in GitHub Desktop, commit, then Push origin.
4. Confirm Render deployment succeeds before testing. Keep existing Meta credentials. Customer brochure delivery requires the WhatsApp template to be approved and correctly configured.
5. Test one chatbot lead and one qualified Vyora lead; verify CRM append-only behavior and the correct customer brief.

## Important
This regeneration does not claim every catalogue project has a verified official brochure. Where the supplied scan did not support a detail, the brief says so. Verify all live prices, availability, approvals, payment plans and possession dates before sharing as current facts.
