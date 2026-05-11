from itertools import count


_plan_counter = count(1)
_action_counter = count(1)


def next_plan_id() -> str:
    return f"plan_{next(_plan_counter):03d}"


def next_action_id() -> str:
    return f"action_{next(_action_counter):03d}"

