-- Cover composite references used by activity and dependency reconciliation.
create index activity_board_item on life_ops.activity(board_id,item_id);
create index dependencies_board_item on life_ops.dependencies(board_id,item_id);
create index dependencies_board_required on life_ops.dependencies(board_id,requires_id);
