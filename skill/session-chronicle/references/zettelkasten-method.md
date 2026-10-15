# Zettelkasten: research and application

Research checked 2026-10-15. This plugin adopts useful Zettelkasten principles for
shared project memory; it does not claim to reproduce Luhmann's personal practice
exactly or to certify methodological compliance with a formal standard.

## Sources

1. **Johannes F. K. Schmidt (2018), “Niklas Luhmann’s Card Index: The Fabrication
   of Serendipity,” Sociologica 12(1), 53–60.**
   DOI: https://doi.org/10.6092/issn.1971-8853/8350
   Full text: https://sociologica.unibo.it/article/download/8350/8270?inline=1
   Historical research by the scientific coordinator of the Luhmann archive.
   Relevant sections: §2 (processing reading notes), §3 (integration), §4 (stable
   numbering), §5 (contextual links and hubs), §6 (entry points), §7 (revisions and
   retained historical notes).
2. **Christian Tietze (2013, updated 2025-08-12), “Create Zettel from Reading Notes
   According to the Principle of Atomicity.”**
   https://zettelkasten.de/posts/create-zettel-from-reading-notes/
   Relevant section: “Phase 3: Write notes from clusters.” This is a practitioner's
   formulation of atomicity as separating concerns to improve reuse and connections.
3. **Sascha Fast (undated online guide, accessed 2026-10-15), “The Complete Guide
   to Atomic Note-Taking.”**
   https://zettelkasten.de/atomicity/guide/
   Relevant sections: “Level 2,” “What is Atomicity?”, “How To Take Atomic Notes,”
   and “Parting Words.” Contemporary practitioner guidance, not a historical
   specification. It explicitly rejects equating atomicity with shortness.

## Findings

**Atomicity is semantic.** Tietze separates concerns so an argument can be reused
independently of other assumptions. Fast describes knowledge building blocks such
as concepts, arguments, models and observations. An argument can need several
sentences and qualifications while still constituting one unit. A short paragraph
listing unrelated mechanisms can be non-atomic. [2, Phase 3; 3, What is Atomicity?]

**Self-contained does not mean context-free.** Notes should contain enough context
to remain understandable later. Deleting necessary assumptions or qualifications
in pursuit of brevity makes a note incomplete. Both incompleteness and unrelated
additional ideas are reasons to revise it. [3, Level 2; What is Atomicity?]

**Connections make individual notes useful.** Schmidt describes structural outlines,
collective references/hubs and single contextual links; Luhmann also revised links
as new cards arrived. Indexes provide entry points rather than replacing the web
of relationships. This supports annotated structure notes and meaningful cross-links
rather than treating tags or a directory tree as the knowledge model. [1, §§5–6]

**Addresses must survive evolution.** Luhmann's numbering gave each card a fixed
address. In a digital collection the corresponding requirement is stable identity
and reliable link resolution; reproducing paper-card numbering is unnecessary for
this plugin. The latter is our engineering interpretation. [1, §4]

**Processing differs from capturing.** Luhmann normally reworked reading records
before integrating them into the collection. The plugin's corresponding design is
to preserve session evidence and synthesize separate idea notes. Session records
are chronological sources, not permanent notes that must each contain one idea.
[1, §2; application to this plugin is a design choice]

**Refinement should preserve history.** Schmidt reports that later revisions did
not remove original cards. This plugin already maintains historical session
evidence; retained topic addresses and refactoring snapshots additionally preserve
what changed when topic prose is revised. Mutable current topic prose is a deliberate
digital adaptation, not a claim that Luhmann rewrote his original cards. [1, §7]

## Product choices, not rules attributed to the method

- English Markdown, kebab-case IDs, YAML metadata and the three note kinds.
- A 300-word configurable review warning; no length-based rejection or truncation.
- A two-distinct-session default for routine materialisation, with explicit
  refactoring permitted to extract an idea supported by one source.
- Deterministic validation of file references and graph integrity plus model-led
  review of coherence, factual support and useful connections.
- A corpus-wide, explicit maintenance command with dry-run, coverage accounting,
  preserved originals and resumable publication through guarded writes.

No count of words, links or headings can establish that a note is accurate or
atomic. Structural findings prioritize review; they do not replace reading and
reasoning about the note and its evidence.
