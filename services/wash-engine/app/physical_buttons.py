"""Only fresh physical button presses select a wash program."""
MODES={'mode_water':'water','mode_osmos':'osmos','mode_nano':'nano',
       'mode_foam':'foam','mode_wax':'wax','mode_chem':'chem'}
BUTTONS=('pause_button',*MODES)

class PhysicalButtons:
    def __init__(self):self.reset()

    def reset(self):self.previous=None

    def action(self,io):
        inputs=io.get('inputs')
        if not isinstance(inputs,dict):self.reset();return None
        held=inputs.get('pause_button') is True
        counts=io.get('input_events')
        if not isinstance(counts,dict) or not all(type(counts.get(k)) is int and counts[k]>=0 for k in BUTTONS):
            self.reset();return 'pause' if held else None
        current={k:counts[k] for k in BUTTONS}
        previous=self.previous;self.previous=current
        if previous is None or any(current[k]<previous[k] for k in BUTTONS):return 'pause' if held else None
        pressed=[k for k in BUTTONS if current[k]>previous[k]]
        # STOP stays dominant while held, including a program chosen on screen.
        if 'pause_button' in pressed or held:
            return 'pause'
        if sum(inputs.get(k) is True for k in MODES)>1:return None
        modes=[k for k in pressed if k in MODES]
        if len(modes)!=1 or current[modes[0]]-previous[modes[0]]!=1:return None
        return MODES[modes[0]]
