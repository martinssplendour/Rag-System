# Chunking Quality Report

Date run: 2026-07-07

Dataset: `kintiga_market_access_candidate_dataset.zip`

Chunking settings used from backend config:

- `CHUNK_SIZE=1000`
- `CHUNK_OVERLAP=150`

The run used the same backend loading and chunking path used by ingestion:

1. Load text by file type.
2. For PDFs, extract grid-line tables first with PyMuPDF `Page.find_tables(strategy="lines")`.
3. Remove detected table bounding boxes from normal PDF prose extraction.
4. Clean whitespace.
5. Strip header and trailer blocks where detected.
6. Extract pipe-delimited TXT/DOCX table rows where available.
7. Split remaining prose by heading-like sections.
8. Split only oversized sections with LangChain `RecursiveCharacterTextSplitter`.
9. Add structured PDF table chunks:
   - one whole-table chunk;
   - one row-level chunk per table row.

## Summary

| File | Type | Chunks | Table chunks | Boundary warnings | Quality result |
| --- | --- | ---: | ---: | ---: | --- |
| `uk_nice_oncology_drug_summary.txt` | TXT | 11 | 0 | 0 | Good |
| `germany_amnog_digital_therapeutic_note_de.txt` | TXT | 13 | 0 | 0 | Good |
| `france_has_medtech_reimbursement_summary.pdf` | PDF | 11 | 5 | 1 | Good |
| `italy_pricing_reimbursement_pathway_note.pdf` | PDF | 12 | 5 | 1 | Good |

## Findings

### UK NICE Oncology TXT

Result: good.

- Header removed: 222 characters.
- Trailer removed: 303 characters.
- Post-cleanup text: 4,366 characters.
- Generated chunks: 11.
- Boundary warnings: 0.
- Pipe-delimited table rows were preserved as one chunk per row.
- Long prose sections were split cleanly with overlap.
- No obvious text cutoff or context loss was detected.

Important chunks:

- Chunks 1-5: key evidence table rows.
- Chunks 7-8: executive summary split into two overlapping chunks.
- Chunk 9: clinical effectiveness discussion.
- Chunk 10: evidence gaps and uncertainty.
- Chunk 11: access and commercial considerations.

### Germany AMNOG TXT

Result: good.

- Header removed: 351 characters.
- Trailer removed: 326 characters.
- Post-cleanup text: 5,809 characters.
- Generated chunks: 13.
- Boundary warnings: 0.
- Pipe-delimited table rows were preserved as separate row chunks.
- Main sections were detected and retained.
- No obvious text cutoff or context loss was detected.

Important chunks:

- Chunks 1-5: evidence table rows.
- Chunks 7-8: summary prose split with overlap.
- Chunks 9-10: evidence overview prose split with overlap.
- Chunks 11-13: benefit, pricing/access, and uncertainty sections.

### France HAS Medtech PDF

Result: good after table-aware PDF extraction.

- Tables detected: 1.
- Table structure: 4 columns, 4 data rows.
- Prose chunks: 6.
- Whole-table chunks: 1.
- Table-row chunks: 4.
- Total chunks: 11.
- Boundary warnings: 1.

Good chunks:

- Executive summary.
- Clinical benefit discussion.
- Access and reimbursement considerations.
- Key uncertainty statement.
- Whole `Evidence and Access Table`.
- Row-level chunks for:
  - clinical outcomes;
  - usability;
  - data governance;
  - economic case.

Example reconstructed row:

```text
Table: Evidence and Access Table
Document: france_has_medtech_reimbursement_summary.pdf
Page: 1

Domain: Data governance.
Submitted evidence: Manufacturer described EEA hosting and role-based access.
Assessment concern: Retention and audit logging needed clarification.
Retrieval signal: privacy concern.
```

Quality note:

The previous tiny fragments such as `Retrieval signal`, `workflow burden`, and `budget impact` are no longer standalone chunks. The table row context is preserved before embedding.

### Italy Pricing Reimbursement PDF

Result: good after table-aware PDF extraction.

- Tables detected: 1.
- Table structure: 4 columns, 4 data rows.
- Prose chunks: 7.
- Whole-table chunks: 1.
- Table-row chunks: 4.
- Total chunks: 12.
- Boundary warnings: 1.

Good chunks:

- Executive summary.
- Clinical and economic evidence.
- Negotiation and access considerations.
- Key uncertainty statement.
- Whole `Evidence and Access Table`.
- Row-level chunks for:
  - clinical benefit;
  - population size;
  - managed access;
  - implementation.

Example reconstructed row:

```text
Table: Evidence and Access Table
Document: italy_pricing_reimbursement_pathway_note.pdf
Page: 1

Domain: Managed access.
Submitted evidence: Outcome-linked agreement with registry follow-up proposed.
Negotiation concern: Definitions of response and renewal need clarity.
Retrieval signal: MEA registry.
```

Quality note:

The previous tiny fragments such as `Retrieval signal`, `Durability beyond two years uncertain`, and `regional access` are no longer standalone chunks. The row-level relationship between domain, evidence, concern, and retrieval signal is preserved.

## Overall Assessment

The chunking logic is now strong for:

- TXT/direct text prose;
- TXT/DOCX pipe-delimited tables;
- born-digital PDF prose;
- born-digital PDF grid-line tables.

No hard truncation was observed in the four files.

The remaining boundary warning in each PDF is a harmless title fragment:

- France: `Reimbursement Summary`
- Italy: `Reimbursement Pathway`

Those are short title continuations, not evidence-bearing table rows. They do not materially affect retrieval quality.

## Engineering Note

The implemented PDF table strategy is deterministic and does not require OCR or an LLM:

```text
PDF page
  -> PyMuPDF line-based table detection
  -> structured table JSON
  -> remove table bounding box from prose extraction
  -> normal prose chunks
  -> whole-table chunk
  -> table-row chunks
  -> embeddings + vector metadata
```

This is the correct first layer for these documents because the PDFs are born-digital and contain visible vector grid lines.

## Table Integrity Verification

Date verified: 2026-07-07

The table extraction was verified against the actual dataset files.

Checks performed:

- extracted table headers match expected visible headers;
- extracted row values match expected visible cell values;
- for PDFs, every expected cell value is present inside the detected PDF table bounding box;
- for PDFs, table headers and fake table fragments are removed from prose extraction;
- whole-table and row-level chunks are created from the structured table;
- for TXT files, raw pipe-delimited rows are preserved exactly in `raw_text`;
- retrieval-friendly semantic row chunks contain every header/value pair.

| File | Table type | Expected rows | Extracted rows | Whole-table chunks | Row chunks | Integrity |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `france_has_medtech_reimbursement_summary.pdf` | PDF grid table | 4 | 4 | 1 | 4 | Passed |
| `italy_pricing_reimbursement_pathway_note.pdf` | PDF grid table | 4 | 4 | 1 | 4 | Passed |
| `uk_nice_oncology_drug_summary.txt` | Pipe-delimited table | 5 | 5 | 0 | 5 | Passed |
| `germany_amnog_digital_therapeutic_note_de.txt` | Pipe-delimited table | 5 | 5 | 0 | 5 | Passed |

Verified France PDF row example:

```text
Domain: Data governance
Submitted evidence: Manufacturer described EEA hosting and role-based access
Assessment concern: Retention and audit logging needed clarification
Retrieval signal: privacy concern
```

Verified Italy PDF row example:

```text
Domain: Managed access
Submitted evidence: Outcome-linked agreement with registry follow-up proposed
Negotiation concern: Definitions of response and renewal need clarity
Retrieval signal: MEA registry
```

Result: table integrity is preserved for the supplied dataset. The extracted structured tables are consistent with the visible tables, and the retrieval chunks preserve the row-level relationship between domain, evidence, concern, and retrieval signal.
