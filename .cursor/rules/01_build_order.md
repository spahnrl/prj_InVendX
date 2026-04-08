# Build order

- Build **forward only**; do not redesign completed modules unless required for **correctness**.
- Preferred order:

  1. Project scaffold  
  2. Config  
  3. Models  
  4. Storage / schema  
  5. HTTP client + robots  
  6. Source discovery  
  7. Crawler  
  8. Parsers  
  9. Scoring  
  10. Reporting  
  11. Tests  

- Do **not** jump ahead to GUI, chatbot, graph DB, or advanced scraping without explicit approval.
- Prefer the **smallest safe** implementation that still allows later extension.
