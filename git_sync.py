"""
코드 저장소 동기화 (git pull / commit / push)

크롤링과는 무관한 일이라 크롤 로직 밖에 둔다. 스케줄러는 예약 크롤의 앞뒤에서
pull() 과 push() 를 부르기만 한다. 어느 쪽이 실패해도 예외를 밖으로 내보내지 않는다.

- data/ 는 .gitignore 로 제외되므로 API 키·DB 는 올라가지 않는다.
"""

import os
import subprocess
from datetime import datetime

REPO_DIR = os.path.dirname(os.path.abspath(__file__))


def _git(args, timeout):
    return subprocess.run(
        ['git', *args], cwd=REPO_DIR, capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=timeout)


def pull():
    """원격의 최신 코드를 받는다 (fast-forward 만). 받은 코드는 서버를 다시 띄워야 적용된다."""
    try:
        result = _git(['pull', '--ff-only'], 30)
        if result.returncode == 0:
            msg = result.stdout.strip()
            if 'Already up to date' in msg:
                print("[git] pull: 이미 최신 버전")
            else:
                print(f"[git] pull: 업데이트됨\n{msg}")
        else:
            print(f"[git] pull 실패 (무시하고 계속): {result.stderr.strip()}")
    except Exception as e:
        print(f"[git] pull 오류 (무시하고 계속): {e}")


def _unpushed_count():
    """원격에 아직 올라가지 않은 커밋 수. 알 수 없으면 0."""
    result = _git(['rev-list', '--count', '@{u}..HEAD'], 15)
    out = result.stdout.strip()
    return int(out) if result.returncode == 0 and out.isdigit() else 0


def push():
    """
    작업 트리에 변경이 있으면 자동 커밋하고, 올라가지 않은 커밋이 있으면 push 한다.

    변경이 없어도 손으로 만든 커밋이 남아 있으면 올린다. (예전에는 작업 트리가
    깨끗하면 바로 끝내서, 손으로 커밋한 것은 다음에 다른 변경이 생길 때까지
    원격에 올라가지 않았다)
    """
    try:
        changed = _git(['status', '--porcelain'], 15).stdout.strip()
        if changed:
            lines = changed.splitlines()
            print(f"[git] push: 변경파일 {len(lines)}개 감지")
            for line in lines[:10]:
                print(f"  {line}")
            _git(['add', '-A'], 15)
            commit_msg = f"auto: Claude Code 수정 반영 [{datetime.now().strftime('%Y-%m-%d %H:%M')}]"
            commit_result = _git(['commit', '-m', commit_msg], 15)
            if commit_result.returncode != 0:
                print(f"[git] commit 실패: {commit_result.stderr.strip()}")
                return

        ahead = _unpushed_count()
        if not ahead:
            print("[git] push: 올릴 커밋 없음 — 스킵")
            return

        push_result = _git(['push'], 60)
        if push_result.returncode == 0:
            print(f"[git] push: GitHub 업로드 완료 (커밋 {ahead}개)")
        else:
            print(f"[git] push 실패 (무시하고 계속): {push_result.stderr.strip()}")
    except Exception as e:
        print(f"[git] push 오류 (무시하고 계속): {e}")
