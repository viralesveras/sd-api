import bob_test_manager

manager = bob_test_manager.get_manager()
manager.connect()

print(f"ID: {manager.get_next_id()}")

