status: done
unit: TD (devnet-teardown.sh in dg-l2)
updated: 2026-11-17T20:30:14Z
completed sections:
- TD code written (dg-l2/devnet-teardown.sh); gates bash -n / shellcheck -x / portability rc 0
- stub tests (scratch TD/out): A dry rc0, B --yes rc0, C again rc0 all absent, D backend-fail rc1 + left list, E --lb-only rc0, F subset rc0 no LB calls, G1-G4 usage rc1, H vm+ssh fail rc1 (wait fix), I no-unit rc0, J txgen TERMINATED rc0
