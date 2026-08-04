# Load-bearing despite being empty: python3 -m bunnyforge.run_tests discovers tests
# with top_level_dir=WORKSPACE, which requires tests/ to be an importable
# package. Deleting this file breaks the entire suite with
# "ImportError: Start directory is not importable".
