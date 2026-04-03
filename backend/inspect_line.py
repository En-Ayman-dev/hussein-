from pathlib import Path
p = Path('c:/Users/Ay/Documents/Prompt/azp/backend/processing/concept_matcher.py')
lines = p.read_text(encoding='utf-8').splitlines()
for i in range(149, 206):
    print(i+1, lines[i])
