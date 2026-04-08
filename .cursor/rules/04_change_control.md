# Change control

- If a change would alter **schema**, **build order**, **storage model**, or **MVP boundaries**, **stop and ask** the user before proceeding.
- If work would expand **outside prj_InVendX** scope, **stop and ask**.
- If a library adds **major complexity**, prefer **stdlib** or a **lightweight** dependency first.
- If something can be done in a **smaller safe step**, choose the smaller step.
- When uncertain, **preserve** the current architecture and add **TODO** markers instead of speculative rewrites.
