# Реестр архитектурных исключений

**Редакция:** 2026-08-27<br>
**Владелец реестра:** technical lead / интегратор программы

Здесь фиксируются только временные отклонения от принятой ADR Bible. Запись не
делает небезопасное состояние допустимым: если обязательный компенсирующий
контроль не подтверждён, применяется fail-closed и работа останавливается.

## EXC-0001. Legacy portal auth выключен по умолчанию

| Поле | Значение |
| --- | --- |
| Статус | active для legacy; не распространяется на новый control plane |
| Нарушаемый принцип | P-14, безопасность fail-closed |
| Область | `backend/app/core/portal_auth.py`, legacy portal и его текущий production deployment |
| Наблюдаемый факт | `PORTAL_AUTH_ENABLED` имеет default `false` |
| Причина | историческая совместимость и локальный режим до появления новой auth boundary |
| Риск | неаутентифицированный доступ к проектным данным и операциям при ошибке perimeter/configuration |
| Владелец | legacy production operator; контроль закрытия — интегратор программы |
| Истекает | 2026-10-08 либо до первого внешнего production canary — что наступит раньше |
| Задачи закрытия | `W0-SEC-01` threat model, `W0-SEC-03` legacy production auth rollout; `W0-ADR-06`/ADR-0010 отдельно проектирует AuthZ нового контура |

Обязательные компенсирующие контроли до закрытия исключения:

1. deployment доступен только через утверждённый private perimeter/reverse
   proxy; этот факт проверяется `W0-SEC-01`, а не предполагается;
2. опасные operator endpoints остаются fail-closed при выключенной portal auth;
3. состояние auth и попытки доступа видимы в журнале и мониторинге;
4. секреты и project payload не публикуются через liveness endpoint;
5. если private perimeter не подтверждён, исключение недействительно и auth
   включается до продолжения эксплуатации.

Критерий удаления EXC-0001: на фактическом legacy production deployment portal
auth включён, а startup policy вне явно обозначенного local/dev mode отклоняет
`false` и неизвестный auth state. Runbook проверяет login/logout, cookie/WS,
открытый liveness, rollback и отсутствие обхода защищённых routes.

Object-level AuthZ нового write API остаётся обязательством ADR-0010 и Gate G2,
но не блокирует закрытие исключения о **полностью выключенной** legacy auth.
После выполнения `W0-SEC-03` запись переводится в `closed`, но не удаляется.
