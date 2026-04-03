from pathlib import Path
p = Path('c:/Users/Ay/Documents/Prompt/azp/unified_ontology.ttl')
lines = p.read_text(encoding='utf-8').splitlines()
for i in range(7330, 7350):
    print(i + 1, lines[i])
