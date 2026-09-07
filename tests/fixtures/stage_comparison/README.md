# Эталоны stage comparison

Каталог содержит минимальный отслеживаемый набор реальных JSON-артефактов,
необходимый детерминированным unit-тестам stage comparison. Эталоны перенесены
из необязательного дерева `experiments/**`, которое намеренно отсутствует в
clean-room по `QUALITY_RUNTIME_CONTRACT_V1.md`.

Исходное происхождение:

- `dense_sectioned_board/*` — `experiments/g2_dense_sectioned_board/*`;
- `system_graph_comparator/comparison_result.json` —
  `experiments/g2_system_graph_comparator/comparison_result.json`;
- `correct_sides_ios/*` — `experiments/g2_4_4_3_correct_sides/ios/*`.

Графы `dense_sectioned_board` совпадают с графами `correct_sides_ios` при
обратной ориентации сторон. Обе пары сохранены намеренно: имена сторон являются
частью семантики соответствующих тестовых сценариев.
