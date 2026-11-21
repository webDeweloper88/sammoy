"""Keep short, debounced button presses until the engine's next poll."""
BUTTONS=('pause_button','mode_water','mode_osmos','mode_nano','mode_foam','mode_wax','mode_chem')

class ButtonEvents:
    def __init__(self,names):
        self.counts={name:0 for name in names if name in BUTTONS}
        self.reset()

    def reset(self):
        # A held button at startup/reconnection must first be released.
        self.ready=set()
        self.previous={}

    def observe(self,inputs,raw_inputs=None):
        for name in self.counts:
            active=inputs.get(name) is True
            raw=(raw_inputs if raw_inputs is not None else inputs).get(name)
            if raw is False:self.ready.add(name)
            elif name in self.ready and not self.previous.get(name,False):
                self.counts[name]+=1
            self.previous[name]=active
        return dict(self.counts)
