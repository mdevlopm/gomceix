"""Small shared widgets/helpers."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Graphene, Gtk, Pango  # noqa: E402


def scrolled_clamp(child, maximum: int = 860):
    """Page body: vertical scrolling, content centred and capped in width."""
    sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
    sw.set_child(Adw.Clamp(maximum_size=maximum, tightening_threshold=600, child=child))
    return sw


def button(label: str, kind: str = "secondary", small: bool = False, **props) -> Gtk.Button:
    """The one button style: primary (accent), secondary (outline), danger, or flat.
    `small` is for buttons that sit inside a row."""
    b = Gtk.Button(label=label, **props)
    b.add_css_class("gx-btn")
    b.add_css_class(f"gx-btn-{kind}")
    if kind == "primary":
        b.add_css_class("suggested-action")
    elif kind == "danger":
        b.add_css_class("destructive-action")
    if small:
        b.add_css_class("gx-btn-small")
        b.set_valign(Gtk.Align.CENTER)
    return b


def menu_item(label: str, icon: str, danger: bool = False) -> Gtk.Button:
    """One entry of a popover menu: icon and label, styled by `popover button.gx-menu-item`."""
    b = Gtk.Button()
    b.add_css_class("gx-menu-item")
    if danger:
        b.add_css_class("danger")
    inner = Gtk.Box(spacing=12)
    inner.append(Gtk.Image.new_from_icon_name(icon))
    # A long entry (a graphics card, a build name) must not make the popover wider than the window.
    text = Gtk.Label(label=label, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END, max_width_chars=40)
    inner.append(text)
    if len(label) > 40:
        b.set_tooltip_text(label)
    b.set_child(inner)
    return b


def row(title: str, subtitle: str = "") -> Adw.ActionRow:
    """ActionRow whose texts are NEVER parsed as Pango markup (names may contain & < >)."""
    return Adw.ActionRow(title=title, subtitle=subtitle, use_markup=False, title_lines=0, subtitle_lines=0)


# ------------------------------------------------------------------ motion
# Adw animations jump straight to their end when animations are switched off
# in the desktop settings, so none of this needs its own "reduce motion" check.
import math  # noqa: E402

from gi.repository import GLib  # noqa: E402


def animate(widget, start: float, end: float, ms: int, apply, easing=None):
    """Run `apply(value)` from start to end over `ms`; returns the animation."""
    anim = Adw.TimedAnimation.new(widget, start, end, ms, Adw.CallbackAnimationTarget.new(apply))
    anim.set_easing(easing or Adw.Easing.EASE_OUT_CUBIC)
    anim.play()
    return anim


def fade_in(widget, ms: int = 420, delay: int = 0):
    """Fade `widget` in the first time it is shown (an unmapped widget cannot animate)."""
    widget.set_opacity(0.0)

    def start(*_args):
        if getattr(widget, "_gx_faded", False):
            return
        widget._gx_faded = True

        def go():
            widget._gx_anim = animate(widget, 0.0, 1.0, ms, widget.set_opacity)
            return False

        GLib.timeout_add(delay, go) if delay else go()

    if widget.get_mapped():
        start()
    else:
        widget.connect("map", start)
    return widget


class ProgressRing(Gtk.DrawingArea):
    """A circular progress indicator in the accent colour that eases to each new value."""

    def __init__(self, size: int = 220, thickness: int = 12):
        super().__init__(content_width=size, content_height=size, halign=Gtk.Align.CENTER)
        self.add_css_class("gx-ring")
        self._thickness = thickness
        self._shown = 0.0
        self._target = 0.0
        self._anim = None
        self.set_draw_func(self._draw)

    @property
    def fraction(self) -> float:
        return self._target

    def set_fraction(self, value: float, ms: int = 450):
        value = min(max(value, 0.0), 1.0)
        if abs(value - self._target) < 1e-4:
            return
        self._target = value

        def apply(v):
            self._shown = v
            self.queue_draw()

        self._anim = animate(self, self._shown, value, ms, apply)

    def _draw(self, _area, cr, width, height):
        rgba = self.get_color()
        cx, cy = width / 2, height / 2
        radius = min(width, height) / 2 - self._thickness
        start = -math.pi / 2
        cr.set_line_cap(1)  # round
        cr.set_line_width(self._thickness)
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.10)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()
        if self._shown <= 0.0:
            return
        end = start + 2 * math.pi * self._shown
        cr.set_line_width(self._thickness + 10)          # soft glow under the bar
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.16)
        cr.arc(cx, cy, radius, start, end)
        cr.stroke()
        cr.set_line_width(self._thickness)
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 1.0)
        cr.arc(cx, cy, radius, start, end)
        cr.stroke()


class ChoiceButton(Gtk.MenuButton):
    """A drop-down that opens straight below itself and scrolls when the list is long.

    `on_changed(index)` fires only for a change the user made.
    """
    MAX_HEIGHT = 280

    def __init__(self, items, selected: int = 0, on_changed=None, placeholder: str = ""):
        super().__init__(direction=Gtk.ArrowType.DOWN, halign=Gtk.Align.START)
        self._placeholder = placeholder      # shown when `selected` is -1: a value that is not in the list
        self.add_css_class("gx-choice")
        self.set_has_frame(False)
        self._on_changed = on_changed
        self._items: list[str] = []
        self._selected = 0
        self._rows: list[Gtk.Button] = []
        self._label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=28)
        content = Gtk.Box(spacing=8)
        content.append(self._label)
        content.append(Gtk.Image.new_from_icon_name("pan-down-symbolic"))
        self.set_child(content)
        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
            max_content_height=self.MAX_HEIGHT, min_content_width=200, child=self._box)
        popover = Gtk.Popover(child=self._scroll, position=Gtk.PositionType.BOTTOM,
                              has_arrow=False, halign=Gtk.Align.START)
        popover.set_offset(0, 8)
        popover.connect("map", lambda *_a: GLib.idle_add(self._reveal_selected))
        self.set_popover(popover)
        self.set_items(items, selected)

    def set_items(self, items, selected: int = 0):
        self._items = list(items)
        child = self._box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._box.remove(child)
            child = nxt
        self._rows = []
        for index, text in enumerate(self._items):
            row = menu_item(text, "object-select-symbolic")
            row.connect("clicked", self._picked, index)
            self._box.append(row)
            self._rows.append(row)
        self.set_selected(selected)

    def selected(self) -> int:
        return self._selected

    def set_selected(self, index: int):
        if not self._items:
            self._selected = 0
            self._label.set_label("—")
            return
        if index < 0 and self._placeholder:
            self._selected = -1
            self._label.set_label(self._placeholder)
            self.set_tooltip_text(None)
        else:
            self._selected = min(max(index, 0), len(self._items) - 1)
            self._label.set_label(self._items[self._selected])
            self.set_tooltip_text(self._items[self._selected] if len(self._items[self._selected]) > 28 else None)
        for i, row in enumerate(self._rows):
            icon = row.get_child().get_first_child()
            icon.set_opacity(1.0 if i == self._selected else 0.0)
            (row.add_css_class if i == self._selected else row.remove_css_class)("chosen")

    def _picked(self, _button, index: int):
        self.get_popover().popdown()
        if index != self._selected:
            self.set_selected(index)
            if self._on_changed:
                self._on_changed(index)

    def _reveal_selected(self):
        if self._rows and self._selected >= 0:
            row = self._rows[self._selected]
            point = row.compute_point(self._box, Graphene.Point().init(0, 0))
            if point[0]:
                adj = self._scroll.get_vadjustment()
                adj.set_value(max(0.0, point[1].y - 48))
        return False


class Segmented(Gtk.Box):
    """Two or more exclusive choices as one pill. `on_changed(value)` fires on user changes."""

    def __init__(self, options, selected: str, on_changed):
        super().__init__(spacing=2, halign=Gtk.Align.START)
        self.add_css_class("gx-seg")
        self._buttons = {}
        group = None
        for value, label in options:
            b = Gtk.ToggleButton(label=label)
            b.add_css_class("gx-seg-item")
            if group is None:
                group = b
            else:
                b.set_group(group)
            b.set_active(value == selected)
            b.connect("toggled", lambda btn, v=value: btn.get_active() and on_changed(v))
            self.append(b)
            self._buttons[value] = b
