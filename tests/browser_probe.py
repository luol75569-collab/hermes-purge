"""Optional Playwright end-to-end panel test against a temporary profile.

Covers the armor additions: the sealed prompt-set selector, an armor apply with an empty
free-text box (the sealed prompt is injected), an explicit set switch, custom-prompt
dirty-invalidation, and byte-exact rollback.
"""
import json
import sys
import tempfile
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from hermes_purge.core import Manager
from hermes_purge.web import make_server

with tempfile.TemporaryDirectory(prefix='purge-browser-') as directory:
    manager = Manager(directory)
    original = b'# browser baseline\nmodel: local/sample\napprovals:\n  mode: manual\n'
    manager.config.write_bytes(original)
    server, token = make_server(manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1360, 'height': 1050})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/#{token}')
                expect(page.locator('#preset')).to_have_value('armor')
                expect(page.locator('#promptset option')).to_have_count(4)  # auto + 3 sealed sets
                expect(page.locator('#armor')).to_contain_text('untrusted-data-boundary')
                expect(page.locator('#apply')).to_be_disabled()

                # Sealed prompt: leave the free-text box empty and apply the armor preset.
                page.locator('#preview').click()
                expect(page.locator('#apply')).to_be_enabled()
                page.locator('#apply').click()
                expect(page.locator('#message')).to_contain_text('应用完成')
                state = manager.status()
                assert state['prompt_set'] == 'armor', state
                assert '小码酱' in state['prompt'], state['prompt'][:80]
                assert state['approval_mode'] == 'off', state

                # Explicit set switch (different model -> different prompt).
                page.locator('#promptset').select_option('armor-lite')
                page.locator('#preview').click()
                expect(page.locator('#apply')).to_be_enabled()
                page.locator('#apply').click()
                expect(page.locator('#message')).to_contain_text('应用完成')
                assert manager.status()['prompt_set'] == 'armor-lite', manager.status()['prompt_set']

                # Custom prompt still wins, and editing invalidates the preview.
                page.locator('#prompt').fill('BROWSER_VERIFIED_RULES')
                page.locator('#preview').click()
                expect(page.locator('#apply')).to_be_enabled()
                page.locator('#prompt').fill('UPDATED_RULES')
                expect(page.locator('#apply')).to_be_disabled()
                page.locator('#preview').click()
                expect(page.locator('#apply')).to_be_enabled()
                page.locator('#apply').click()
                expect(page.locator('#message')).to_contain_text('应用完成')
                assert manager.status()['prompt'] == 'UPDATED_RULES'

                # Rollback is byte-exact, one LIFO step per applied transaction.
                for _ in range(5):
                    if manager.config.read_bytes() == original:
                        break
                    page.once('dialog', lambda dialog: dialog.accept())
                    page.locator('#revert').click()
                    expect(page.locator('#result')).to_contain_text('reverted')
                assert manager.config.read_bytes() == original, manager.config.read_bytes()
                page.reload()
                expect(page.locator('#prompt')).to_have_value('')

                output = Path(__file__).resolve().parents[1] / 'docs' / 'panel.png'
                output.parent.mkdir(parents=True, exist_ok=True)
                page.locator('#preview').click()
                page.screenshot(path=str(output), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'mobile overflow'
                assert not errors, errors
                print(json.dumps({'browser': 'Chromium', 'sealed_sets_listed': 3,
                                  'armor_apply_uses_sealed_prompt': True,
                                  'prompt_set_switch': True, 'preview': True,
                                  'dirty_invalidates_preview': True, 'apply': True,
                                  'reload_auth': True, 'revert_exact': True,
                                  'mobile_no_overflow': True, 'page_errors': errors}, indent=2))
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
