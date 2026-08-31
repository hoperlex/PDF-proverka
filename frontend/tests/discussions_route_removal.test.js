import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, '..');
const appJs = fs.readFileSync(path.join(frontendRoot, 'static/js/app.js'), 'utf8');
const html = fs.readFileSync(path.join(frontendRoot, 'index.html'), 'utf8');

// Раздел «Проработка замечаний» удалён коммитом aeb0b2f2 вместе с обоими
// роут-хендлерами `/project/:id/discussions[/:item]`. Сообщение того коммита
// утверждало «0 остаточных ссылок на discussions» — утверждение было неверным:
// closeDiscussion() продолжала уводить на удалённый маршрут, и хеш проваливался
// в замыкающую ветвь `/^\/project\/(.+)$/`, после чего currentProjectId
// становился строкой «{id}/discussions», а loadProject грузил несуществующий
// проект. Дефект зафиксирован как RI-1 в
// docs/architecture/WEB_ROUTE_INVENTORY_V1.md и исправлен в W0-WEB-02.
//
// Тест закрывает именно ту дыру, из-за которой дефект прожил два месяца
// незамеченным: ни один тест не проверял, что удалённый маршрут действительно
// перестал быть целью навигации.

describe('удалённый маршрут /discussions не является целью навигации', () => {
  it('ни одна навигация в app.js не ведёт на /discussions', () => {
    // Ловим и navigate('...'), и прямое присваивание location.hash.
    const navigationTargets = [
      ...appJs.matchAll(/navigate\(\s*([^;]*?)\)\s*;/g),
      ...appJs.matchAll(/location\.hash\s*=\s*([^;]*?);/g),
    ].map(match => match[1]);

    const offenders = navigationTargets.filter(target => target.includes('discussions'));
    expect(offenders).toEqual([]);
  });

  it('в разметке нет ссылок на удалённый маршрут', () => {
    expect(html).not.toContain('/discussions');
  });

  it('диспетчер не разбирает маршрут discussions', () => {
    // Обратная сторона того же решения: если ветвь вернут, вернуть надо и
    // весь раздел, а не только навигацию к нему.
    expect(appJs).not.toContain('/discussions$/');
    expect(appJs).not.toContain("currentView.value = 'discussions'");
  });

  it('closeDiscussion сохранена и по-прежнему сбрасывает состояние', () => {
    // Удалять функцию было нельзя: её зовёт resolveDiscussion, а
    // backend-роутер /api/discussions/**/resolve всё ещё используется
    // экспертной оценкой. Проверяем, что исправление сняло навигацию, а не
    // выкинуло работающий код.
    const body = appJs.match(/function closeDiscussion\(\)\s*\{[\s\S]*?\n {8}\}/);
    expect(body, 'closeDiscussion исчезла из app.js').not.toBeNull();
    expect(body[0]).toContain('activeDiscussion.value = null');
    expect(body[0]).toContain('loadDiscussionItems(');
    expect(body[0]).not.toContain('navigate(');
  });
});
