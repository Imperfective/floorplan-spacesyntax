"""공유 Caddyfile(deepvoice-caddy)에서 sapcesyntax.com 블록만 바꾼다 — 서버에서 python3 로 실행.

    python3 apply.py <Caddyfile> <새 블록 파일> [--gate] [--dry-run]

다른 사이트 블록은 건드리지 않는다. --gate 면 '#GATE ' 접두어를 떼어 로그인 관문을 켠다.
결과 전체를 표준 출력으로 내보내므로(--dry-run), 검증은 호출하는 쪽에서 caddy validate 로 한다.
"""
import sys

path, block_path = sys.argv[1], sys.argv[2]
gate, dry = "--gate" in sys.argv, "--dry-run" in sys.argv
text = open(path, encoding="utf-8").read()
block = open(block_path, encoding="utf-8").read().rstrip("\n") + "\n"
if gate:
    block = "\n".join(line.replace("#GATE ", "", 1) if line.lstrip().startswith("#GATE ") else line for line in block.split("\n"))

lines = text.split("\n")
start = next(i for i, l in enumerate(lines) if l.strip() == "sapcesyntax.com {")
depth, end = 0, None
for i in range(start, len(lines)):
    depth += lines[i].count("{") - lines[i].count("}")
    if depth == 0:
        end = i
        break
if end is None:
    sys.exit("sapcesyntax.com 블록의 끝을 찾지 못했습니다")
new = "\n".join(lines[:start]) + "\n" + block + "\n".join(lines[end + 1:])
if dry:
    sys.stdout.write(new)
else:
    with open(path, "r+", encoding="utf-8") as f:   # 단일 파일 바인드 마운트라 이름 바꾸기 대신 제자리에 쓴다
        f.seek(0)
        f.write(new)
        f.truncate()
