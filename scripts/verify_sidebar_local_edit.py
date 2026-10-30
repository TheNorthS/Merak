"""Real browser sidebar clicks and model proposal; isolated completed-state fixture only."""

import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def project_fixture() -> tuple[Path, bytes]:
    from server.contracts.workflow_nodes import WORKFLOW_NODES
    project = ROOT/'output'/f'sidebar-local-edit-validation-{time.time_ns()}'
    if project.exists():
        raise ValueError('UI validation uses a new isolated fixture directory')
    (project/'paper/sections').mkdir(parents=True)
    (project/'paper/sections/01_introduction.tex').write_text(
        '\\section{Introduction}\nOur protocol compares declared channel layouts.\n', encoding='utf-8')
    (project/'paper/main.tex').write_text('\\documentclass{article}\n\\begin{document}\n'
        '\\input{sections/01_introduction.tex}\n\\end{document}\n', encoding='utf-8')
    state = {'run_id': 'sidebar-validation', 'status': 'completed', 'execution_completed': True,
        'completion_class': 'reviewable_draft_ready', 'submission_ready': False,
        'phases': {node['id']: {'status': 'accepted', 'verdict_id': 'fixture-prior', 'details': {}}
                   for node in WORKFLOW_NODES}, 'validation_fixture': True}
    path = project/'.merak/runs/sidebar-validation.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    return project, path.read_bytes()


def verify_browser(project: Path, before_run: bytes, password: str) -> dict:
    from playwright.sync_api import sync_playwright
    target = project/'paper/sections/01_introduction.tex'
    before = target.read_bytes()
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(
            ('http://127.0.0.1:', 'http://localhost:')) else route.abort())
        context.add_init_script('localStorage.setItem("merak-ide:projectPath", ' + json.dumps(str(project)) + ');')
        page = context.new_page();errors=[]
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:5178')
        page.get_by_label('用户名', exact=True).fill('sidebar-validation')
        page.get_by_label('密码', exact=True).fill(password)
        page.get_by_role('button', name='登录', exact=True).click()
        page.get_by_role('button', name='对话', exact=True).wait_for(timeout=30000)
        connection = context.request.post('http://127.0.0.1:8011/api/settings/models/test?provider=openai-api', timeout=100000)
        assert connection.ok and connection.json().get('success') is True, 'Real model connection test failed'
        page.reload()
        page.get_by_role('button', name='对话', exact=True).click(timeout=30000)
        composer = page.locator('.merak-chat-panel textarea')
        composer.fill('关闭验证草稿')
        page.get_by_role('button', name='关闭对话面板', exact=True).click()
        assert not composer.is_visible()
        page.get_by_role('button', name='对话', exact=True).click()
        assert composer.input_value() == '关闭验证草稿'
        page.screenshot(path=str(ROOT/'output/sidebar-close-reopen.png'))
        composer.fill('请编辑 paper/sections/01_introduction.tex，只把句子 "Our protocol compares declared channel layouts." '
            '改为 "Our protocol compares explicitly declared channel layouts."。只提出这一处 Edit 修改，不修改其他文件，不运行任何工作流。')
        send = page.get_by_role('button', name='发送消息', exact=True)
        from playwright.sync_api import expect
        expect(send).to_be_enabled(timeout=30000)
        page.wait_for_timeout(1000)
        send.click()
        approve = page.get_by_role('button', name='批准', exact=True)
        approve.wait_for(state='visible', timeout=180000)
        assert target.read_bytes() == before
        page.screenshot(path=str(ROOT/'output/sidebar-edit-proposal.png'))
        approve.click()
        page.get_by_text('局部修改已保存；已完成工作流保持不变', exact=True).first.wait_for(timeout=30000)
        assert 'explicitly declared' in target.read_text(encoding='utf-8')
        assert (project/'.merak/runs/sidebar-validation.json').read_bytes() == before_run
        revisions = list((project/'.merak/local-revisions').glob('*.json'))
        assert len(revisions) == 1 and json.loads(revisions[0].read_bytes())['scheduled_nodes'] == []
        baseline = project/'.merak/completed-versions/sidebar-validation/artifacts/paper/sections/01_introduction.tex'
        assert baseline.read_bytes() == before
        assert not errors, errors
        page.screenshot(path=str(ROOT/'output/sidebar-edit-applied.png'))
        browser.close()
    return {'accepted': True, 'real_browser_clicks': True, 'real_model': True, 'run_state_is_fixture': True,
        'closed_and_reopened_draft_preserved': True, 'proposal_staged_before_approval': True,
        'completed_run_bytes_unchanged': True, 'scheduled_nodes': [], 'page_errors': errors,
        'before_file_sha256': hashlib.sha256(before).hexdigest(), 'after_file_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}


if __name__ == '__main__':
    project, before_run = project_fixture()
    password = secrets.token_urlsafe(32)
    env = {**os.environ, 'PYTHONUTF8': '1',
        'MERAK_IDE_DATABASE_URL': 'sqlite+aiosqlite:///' + (project/'ui-auth.db').as_posix(),
        'MERAK_SIDEBAR_TEST_PASSWORD': password}
    seed = '''import asyncio,os
from server.db.engine import init_db,AsyncSessionLocal,engine
from server.services.authentication import authentication_service
from server.models.models import UserRole
async def seed():
 await init_db()
 async with AsyncSessionLocal() as session:
  user=await authentication_service.register(session,username='sidebar-validation',email='sidebar@validation.local',password=os.environ['MERAK_SIDEBAR_TEST_PASSWORD'])
  user.role=UserRole.ADMIN
  await session.commit()
 await engine.dispose()
asyncio.run(seed())
'''
    subprocess.run([sys.executable, '-B', '-c', seed], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    with (ROOT/'output/sidebar-ui-backend.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, '-B', '-m', 'uvicorn', 'server.main:app',
            '--host', '127.0.0.1', '--port', '8011'], cwd=ROOT, env=env, stdout=log, stderr=log,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            for _ in range(40):
                if process.poll() is not None:
                    raise RuntimeError('Isolated UI backend exited before readiness')
                try:
                    urllib.request.urlopen('http://127.0.0.1:8011/health', timeout=1);break
                except OSError:
                    time.sleep(.5)
            result = verify_browser(project, before_run, password)
            (project/'UI_VERIFICATION.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result))
        finally:
            process.terminate();process.wait(timeout=15)
