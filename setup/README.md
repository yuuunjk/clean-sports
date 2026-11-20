# 워크플로 한 번만 등록해 주세요

Pickle의 GitHub 연결에는 **워크플로 파일 쓰기(workflows) 권한이 없어서**,
`.github/workflows/update-sports.yml`만 자동으로 올릴 수 없습니다. 이 파일 하나만 등록하면 나머지는 자동입니다.

## 방법 A — 워크플로 권한을 켜기 (권장, 클릭 1번)

Pickle 앱 → **My Pickle → Connections → GitHub** 에서 **Actions(워크플로) 쓰기**를 켜 주세요.
켜 주시면 이 파일은 Pickle이 직접 올립니다.

## 방법 B — 웹에서 붙여넣기 (2분)

1. https://github.com/yuuunjk/clean-sports/new/main?filename=.github%2Fworkflows%2Fupdate-sports.yml 열기
2. 이 폴더의 `update-sports.yml` 내용을 **그대로 복사해서 붙여넣기**
3. 아래 **Commit changes** 누르기

커밋되면 바로 첫 실행이 시작되고, Pages도 자동으로 켜집니다.
