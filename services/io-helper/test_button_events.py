import unittest
from button_events import ButtonEvents

class ButtonEventTests(unittest.TestCase):
    def test_initial_held_contact_requires_release_and_fresh_press(self):
        b=ButtonEvents(['mode_water'])
        self.assertEqual(b.observe({'mode_water':True})['mode_water'],0)
        b.observe({'mode_water':False})
        self.assertEqual(b.observe({'mode_water':True})['mode_water'],1)
        self.assertEqual(b.observe({'mode_water':True})['mode_water'],1)
    def test_short_press_is_retained_after_release_and_disconnect_is_disarmed(self):
        b=ButtonEvents(['mode_foam']);b.observe({'mode_foam':False})
        b.observe({'mode_foam':True})
        self.assertEqual(b.observe({'mode_foam':False})['mode_foam'],1)
        b.reset()
        self.assertEqual(b.observe({'mode_foam':True})['mode_foam'],1)
        b.observe({'mode_foam':False})
        self.assertEqual(b.observe({'mode_foam':True})['mode_foam'],2)

    def test_debounce_startup_false_does_not_arm_a_held_button(self):
        b=ButtonEvents(['mode_water'])
        b.observe({'mode_water':False},{'mode_water':True})
        self.assertEqual(b.observe({'mode_water':True},{'mode_water':True})['mode_water'],0)
