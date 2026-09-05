# Deterministic DNS unit fixture

Some developer networks synthesize FakeIP answers even for nonexistent or reserved
`.invalid` names. The negative DNS unit test now installs the existing upstream
`TestDnsResolver`, verifies a known answer, then verifies the unknown name is empty.
The production resolver is unchanged. `ResolveLocalhost` and system nameserver
inspection still exercise the host resolver. Real-world NXDOMAIN policy belongs
to network integration testing and is not guaranteed by the host-independent unit.
