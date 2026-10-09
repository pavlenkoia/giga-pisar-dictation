"""Enumerate GStreamer audio sources without creating a capture pipeline."""
from __future__ import annotations


def _structure_string(structure, key):
    """Gst.Structure.get_string returns str|None (unlike PyGObject get())."""
    return structure.get_string(key)


def _add_audio_source_filter(gst, monitor):
    monitor.add_filter("Audio/Source", gst.Caps.from_string("audio/x-raw"))


def list_audio_sources(gst=None):
    if gst is None:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst as gst
        gst.init(None)
    monitor = gst.DeviceMonitor.new()
    if monitor is None:
        raise RuntimeError("Не удалось создать список аудиоустройств")
    _add_audio_source_filter(gst, monitor)
    if not monitor.start():
        raise RuntimeError("Не удалось перечислить аудиоустройства")
    try:
        devices = []
        seen_ids = set()
        for device in monitor.get_devices():
            properties = device.get_properties()
            # PulseAudio does not expose its internal source ID in the public
            # Gst.Structure; it is a separate GstDevice property copied to pulsesrc.
            device_class = _structure_string(properties, "device.class") if properties else None
            if device_class and "monitor" in device_class.lower():
                continue
            # Device.create_element constructs but does not start a source. Its
            # pulsesrc.device property is the authoritative compatible identifier.
            element = device.create_element(None)
            if element is None:
                continue
            factory = element.get_factory()
            if factory is None or factory.get_name() != "pulsesrc":
                continue
            device_id = element.get_property("device")
            if not device_id or device_id in seen_ids:
                continue
            seen_ids.add(device_id)
            devices.append((device_id, device.get_display_name() or device_id))
        counts = {}
        for _, name in devices:
            counts[name] = counts.get(name, 0) + 1
        return [(device_id, f"{name} ({device_id})" if counts[name] > 1 else name)
                for device_id, name in devices]
    finally:
        monitor.stop()
