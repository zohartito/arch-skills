SkillEvaluator 0.9.0 (NVIDIA, Apache-2.0, commit ae7e858), run 2026-11-15 on all nine skills. Tier 1: `tier1 <skill> --no-llm --checks schema,version,pii,license,code-integrity,unicode,quality,lint` (no LLM; the SkillSpector security scan and the dependency audit were not run). Similarity: `similarity-check skills` with local Ollama `nomic-embed-text` embeddings (no external calls), default threshold 0.75, which was tuned for NVIDIA's own embedding model, so scores from nomic run high.

## Tier 1 (keyless static checks)

| Skill | Status | Quality | Critical/High/Medium/Low | Most serious finding |
|---|---|---|---|---|
| sun-study | failed | 86.8 (B) | 0/1/2/5 | high yaml_syntax: Invalid YAML syntax in frontmatter: mapping values are not allowed here |
| printables-entourage | passed | 79.0 (C) | 0/0/6/11 | medium body_recommended_section: Missing recommended section: '## Instructions' |
| model-assembly-sheet | passed | 80.2 (B) | 0/0/6/11 | medium body_recommended_section: Missing recommended section: '## Instructions' |
| physical-model-prep | passed | 80.2 (B) | 0/0/6/12 | medium body_recommended_section: Missing recommended section: '## Instructions' |
| stl-fit-and-repair | passed | 81.5 (B) | 0/0/6/12 | medium body_recommended_section: Missing recommended section: '## Instructions' |
| precedent-dossier | passed | 83.2 (B) | 0/0/6/9 | medium body_recommended_section: Missing recommended section: '## Instructions' |
| sheet-review | passed | 83.2 (B) | 0/0/6/9 | medium body_recommended_section: Missing recommended section: '## Instructions' |
| bambu-print-recipes | passed | 86.0 (B) | 0/0/4/9 | medium body_recommended_section: Missing recommended section: '## Instructions' |
| rhino-safe-capture | passed | 87.2 (B) | 0/0/4/10 | medium body_recommended_section: Missing recommended section: '## Instructions' |

## Similarity between skills (descriptions)

Status incomplete; incomplete: collection-coverage.

| Pair | Class | Score |
|---|---|---|
| bambu-print-recipes / printables-entourage | SIMILAR | 0.777 |
| bambu-print-recipes / stl-fit-and-repair | SIMILAR | 0.763 |
| physical-model-prep / printables-entourage | SIMILAR | 0.763 |
| physical-model-prep / stl-fit-and-repair | SIMILAR | 0.756 |

## Similarity between skills (full-body)

Status failed; incomplete: collection-coverage.

| Pair | Class | Score |
|---|---|---|
| bambu-print-recipes / stl-fit-and-repair | HIGH_SIMILARITY | 0.919 |
| bambu-print-recipes / physical-model-prep | HIGH_SIMILARITY | 0.914 |
| physical-model-prep / stl-fit-and-repair | HIGH_SIMILARITY | 0.913 |
| physical-model-prep / printables-entourage | SIMILAR | 0.894 |
| model-assembly-sheet / physical-model-prep | SIMILAR | 0.891 |
| printables-entourage / stl-fit-and-repair | SIMILAR | 0.882 |
| bambu-print-recipes / printables-entourage | SIMILAR | 0.879 |
| bambu-print-recipes / model-assembly-sheet | SIMILAR | 0.874 |
| model-assembly-sheet / stl-fit-and-repair | SIMILAR | 0.862 |
| physical-model-prep / sheet-review | SIMILAR | 0.860 |
| model-assembly-sheet / printables-entourage | SIMILAR | 0.858 |
| physical-model-prep / precedent-dossier | SIMILAR | 0.830 |
| precedent-dossier / sheet-review | SIMILAR | 0.828 |
| sheet-review / stl-fit-and-repair | SIMILAR | 0.817 |
| model-assembly-sheet / precedent-dossier | SIMILAR | 0.812 |
| model-assembly-sheet / sheet-review | SIMILAR | 0.803 |
| rhino-safe-capture / stl-fit-and-repair | SIMILAR | 0.799 |
| bambu-print-recipes / sheet-review | SIMILAR | 0.799 |
| precedent-dossier / printables-entourage | SIMILAR | 0.799 |
| precedent-dossier / stl-fit-and-repair | SIMILAR | 0.798 |
| printables-entourage / rhino-safe-capture | SIMILAR | 0.798 |
| physical-model-prep / rhino-safe-capture | SIMILAR | 0.795 |
| printables-entourage / sheet-review | SIMILAR | 0.793 |
| precedent-dossier / rhino-safe-capture | SIMILAR | 0.793 |
| bambu-print-recipes / precedent-dossier | SIMILAR | 0.781 |
| rhino-safe-capture / sheet-review | SIMILAR | 0.775 |
| bambu-print-recipes / rhino-safe-capture | SIMILAR | 0.766 |

## Reading this report

- The one real defect: `sun-study/SKILL.md` frontmatter is not strict YAML. Its unquoted `description` contains
  `Direct sun only: not for ...`, and a colon followed by a space inside a plain scalar is a mapping error. Claude Code
  loaded the skill anyway in the trigger sweep, but strict parsers (SkillEvaluator, and any other YAML loader) reject
  it, which is also why sun-study is missing from both similarity scans. Quoting the description fixes it. Not edited here.
- The remaining medium findings are conventions of NVIDIA's template (`## Instructions`, `## Examples` headings,
  `metadata.author` / `metadata.tags`, a scripts table, `run_script()` examples), not errors under the Agent Skills
  specification. No PII, licence, Unicode or script-lint finding was above low.
- Similarity: descriptions put the fabrication skills (bambu-print-recipes, physical-model-prep, printables-entourage,
  stl-fit-and-repair) closest together, which matches their shared subject. The full-body scan flags nearly every pair,
  including sheet-review with printables-entourage; with `nomic-embed-text` at the default 0.75 threshold that is
  noise, not overlap. Treat only the description pairs as a lead, and re-run with the tool's default embedding model
  before acting on any pair.
