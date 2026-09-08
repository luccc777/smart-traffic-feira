"""Os controladores concretos que implementam o C3.

`ControladorTimer` e `ControladorRL` são os dois braços que a bancada de medição
precisa para existir (agente A2). O `ControladorHumano` é do agente A3 e o
baseline coordenado (Webster + offsets) é do A5 — os dois entram aqui, e na
suíte de conformidade, quando forem entregues.

Nada é importado ansiosamente: `ControladorRL` puxa `sim`/`torch` só dentro do
`reset()`, para importar este pacote não congelar `sim.environment.constants`
antes de `Cenario.aplicar()` (a armadilha documentada no C1).
"""
from .coordenado import ControladorCoordenado, PlanoFixo
from .humano import ControladorHumano
from .rl import ControladorRL
from .timer import ControladorTimer

__all__ = ["ControladorRL", "ControladorTimer", "ControladorCoordenado",
           "PlanoFixo", "ControladorHumano"]
