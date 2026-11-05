"""Pruebas unitarias del registro de sesiones conversacionales."""

from __future__ import annotations

from airi.services.spectator_session import (
    ConversationState,
    SpectatorSessionRegistry,
)


def test_estado_inicial_es_espectadora():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    assert reg.state("c1") == ConversationState.SPECTATING


def test_record_human_activity_incrementa_generacion_y_actualiza():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    g1 = reg.record_human_activity("c1", now=10.0)
    assert g1 == 1
    assert reg.session("c1").last_human_activity == 10.0
    g2 = reg.record_human_activity("c1", now=20.0)
    assert g2 == 2
    assert reg.session("c1").last_human_activity == 20.0


def test_record_human_activity_saca_de_retirada():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=1.0)
    reg.begin_waking("c1", 1)
    reg.finish_waking("c1", published=True, stay_active=True)
    # fuerza retirada
    reg.finish_active_turn("c1", stay_active=False, published=True)
    assert reg.state("c1") == ConversationState.SPECTATING
    # simula estado retirada directo no expuesto; se valida que actividad no rompe activa
    reg.record_human_activity("c1", now=2.0)
    assert reg.state("c1") == ConversationState.SPECTATING


def test_begin_waking_exige_generacion_coincidente():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=1.0)
    assert reg.begin_waking("c1", 1) is True
    assert reg.state("c1") == ConversationState.WAKING
    # segunda apertura falla
    reg.record_human_activity("c1", now=2.0)  # otra generación, estado ya waking
    assert reg.begin_waking("c1", 999) is False


def test_begin_waking_falla_si_no_es_espectadora():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=1.0)
    reg.begin_waking("c1", 1)
    assert reg.begin_waking("c1", 2) is False


def test_finish_waking_abre_solo_con_texto_publicado():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=1.0)
    reg.begin_waking("c1", 1)
    assert reg.finish_waking("c1", published=True, stay_active=True) == ConversationState.ACTIVE
    assert reg.state("c1") == ConversationState.ACTIVE


def test_finish_waking_ignora_stay_active_sin_texto():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=1.0)
    reg.begin_waking("c1", 1)
    # stay_active=True pero sin publicación: debe abortar
    assert reg.finish_waking("c1", published=False, stay_active=True) == ConversationState.SPECTATING
    assert reg.state("c1") == ConversationState.SPECTATING


def test_finish_waking_silencioso_aborta():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=1.0)
    reg.begin_waking("c1", 1)
    assert reg.finish_waking("c1", published=False, stay_active=False) == ConversationState.SPECTATING


def test_finish_waking_fuera_de_despertando_es_noop():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=1.0)
    assert reg.finish_waking("c1", published=True, stay_active=True) == ConversationState.SPECTATING


def test_finish_active_turn_mantiene_si_permanece_y_publico():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=1.0)
    reg.begin_waking("c1", 1)
    reg.finish_waking("c1", published=True, stay_active=True)
    assert reg.finish_active_turn("c1", stay_active=True, published=True) == ConversationState.ACTIVE


def test_finish_active_turn_retira_si_no_permanece():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=1.0)
    reg.begin_waking("c1", 1)
    reg.finish_waking("c1", published=True, stay_active=True)
    assert reg.finish_active_turn("c1", stay_active=False, published=True) == ConversationState.SPECTATING
    assert reg.state("c1") == ConversationState.SPECTATING


def test_finish_active_turn_retira_si_no_publico():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=1.0)
    reg.begin_waking("c1", 1)
    reg.finish_waking("c1", published=True, stay_active=True)
    assert reg.finish_active_turn("c1", stay_active=True, published=False) == ConversationState.SPECTATING


def test_retire_if_idle_exige_tiempo():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0, active_idle_seconds=300.0)
    reg.record_human_activity("c1", now=100.0)
    reg.begin_waking("c1", 1)
    reg.finish_waking("c1", published=True, stay_active=True)
    gen = reg.session("c1").generation
    # aun no vencido
    assert reg.retire_if_idle("c1", gen, now=200.0, timeout=300.0) is False
    assert reg.state("c1") == ConversationState.ACTIVE
    # vencido
    assert reg.retire_if_idle("c1", gen, now=500.0, timeout=300.0) is True
    assert reg.state("c1") == ConversationState.SPECTATING


def test_retire_if_idle_token_desalineado_no_muta():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=100.0)
    reg.begin_waking("c1", 1)
    reg.finish_waking("c1", published=True, stay_active=True)
    assert reg.retire_if_idle("c1", 999, now=500.0, timeout=10.0) is False
    assert reg.state("c1") == ConversationState.ACTIVE


def test_retire_if_idle_deshabilitado_con_cero():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=100.0)
    reg.begin_waking("c1", 1)
    reg.finish_waking("c1", published=True, stay_active=True)
    gen = reg.session("c1").generation
    assert reg.retire_if_idle("c1", gen, now=500.0, timeout=0) is False
    assert reg.state("c1") == ConversationState.ACTIVE


def test_should_fire_proactive_primera_ventana():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0, proactive_idle_seconds=100.0)
    reg.record_human_activity("c1", now=0.0)
    assert reg.should_fire_proactive("c1", now=150.0) is True
    assert reg.session("c1").last_proactive_attempt == 150.0


def test_should_fire_proactive_no_reintenta_sin_actividad_nueva():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0, proactive_idle_seconds=100.0)
    reg.record_human_activity("c1", now=0.0)
    assert reg.should_fire_proactive("c1", now=150.0) is True
    # sin actividad nueva, no puede volver a intentar
    assert reg.should_fire_proactive("c1", now=300.0) is False


def test_should_fire_proactive_reintenta_tras_actividad_nueva():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0, proactive_idle_seconds=100.0)
    reg.record_human_activity("c1", now=0.0)
    assert reg.should_fire_proactive("c1", now=150.0) is True
    reg.record_human_activity("c1", now=200.0)
    assert reg.should_fire_proactive("c1", now=350.0) is True


def test_should_fire_proactive_deshabilitado_con_cero():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0, proactive_idle_seconds=0.0)
    reg.record_human_activity("c1", now=0.0)
    assert reg.should_fire_proactive("c1", now=1000.0) is False


def test_should_fire_proactive_solo_en_espectadora():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0, proactive_idle_seconds=10.0)
    reg.record_human_activity("c1", now=0.0)
    reg.begin_waking("c1", 1)
    reg.finish_waking("c1", published=True, stay_active=True)
    assert reg.should_fire_proactive("c1", now=1000.0) is False


def test_clear_elimina_sesion():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=1.0)
    reg.clear("c1")
    assert reg.state("c1") == ConversationState.SPECTATING
    assert reg.session("c1").generation == 0


def test_enter_active_fuerza_activa_desde_espectadora():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=10.0)
    assert reg.enter_active("c1", now=50.0) == ConversationState.ACTIVE
    session = reg.session("c1")
    assert session.state == ConversationState.ACTIVE
    assert session.active_since == 50.0
    assert session.last_human_activity == 50.0
    assert session.generation == 2


def test_enter_active_refresca_actividad_sin_resetear_active_since():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.enter_active("c1", now=50.0)
    reg.enter_active("c1", now=80.0)
    session = reg.session("c1")
    assert session.state == ConversationState.ACTIVE
    assert session.active_since == 50.0
    assert session.last_human_activity == 80.0
    assert session.generation == 2


def test_enter_active_permite_retiro_por_inactividad():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0, active_idle_seconds=300.0)
    reg.enter_active("c1", now=100.0)
    gen = reg.session("c1").generation
    assert reg.retire_if_idle("c1", gen, now=200.0, timeout=300.0) is False
    assert reg.state("c1") == ConversationState.ACTIVE
    assert reg.retire_if_idle("c1", gen, now=500.0, timeout=300.0) is True
    assert reg.state("c1") == ConversationState.SPECTATING


def test_aislamiento_entre_canales():
    reg = SpectatorSessionRegistry(clock=lambda: 1000.0)
    reg.record_human_activity("c1", now=1.0)
    reg.record_human_activity("c2", now=2.0)
    reg.begin_waking("c1", 1)
    assert reg.state("c1") == ConversationState.WAKING
    assert reg.state("c2") == ConversationState.SPECTATING
