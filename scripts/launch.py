import sys

if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
    from clipper.selftest import run_selftest
    raise SystemExit(run_selftest(sys.argv[2]))
if len(sys.argv) == 3 and sys.argv[1] == '--self-test-ui':
    from clipper.selftest import run_ui_selftest
    raise SystemExit(run_ui_selftest(sys.argv[2]))

from clipper.app import main
raise SystemExit(main())
