"""
Waveform cleaning algorithms (smoothing, filtering, baseline subtraction)
"""

from traitlets import Int, CaselessStrEnum
from ctapipe.core import Component, Factory
import numpy as np
from scipy.signal import general_gaussian
from abc import abstractmethod
from ctapipe.image.charge_extractors import AverageWfPeakIntegrator,\
    LocalPeakIntegrator

__all__ = ['WaveformCleanerFactory', 'CHECMWaveformCleanerAverage',
           'CHECMWaveformCleanerLocal',
           'NullWaveformCleaner']


class WaveformCleaner(Component):
    """
    Base component to handle the cleaning of the waveforms in an image.

    Parameters
    ----------
    config : traitlets.loader.Config
        Configuration specified by config file or cmdline arguments.
        Used to set traitlet values.
        Set to None if no configuration to pass.
    tool : ctapipe.core.Tool or None
        Tool executable that is calling this component.
        Passes the correct logger to the component.
        Set to None if no Tool to pass.
    kwargs
    """

    name = 'WaveformCleaner'

    def __init__(self, config, tool, **kwargs):
        super().__init__(config=config, parent=tool, **kwargs)

    @abstractmethod
    def apply(self, waveforms):
        """
        Apply the cleaning method to the waveforms
        
        Parameters
        ----------
        waveforms : ndarray
            Waveforms stored in a numpy array of shape
            (n_chan, n_pix, n_samples).

        Returns
        -------
        cleaned : ndarray
            Cleaned waveforms stored in a numpy array of shape
            (n_chan, n_pix, n_samples).

        """
        pass


class NullWaveformCleaner(WaveformCleaner):
    """
    Dummy waveform cleaner that simply returns its input
    """
    name = 'NullWaveformCleaner'

    def apply(self, waveforms):
        return waveforms


class CHECMWaveformCleaner(WaveformCleaner):
    """
    Waveform cleaner used by CHEC-M.

    This cleaner performs 2 basline subtractions: a simple subtraction
    using the average of the first 32 samples in the waveforms, then a 
    convolved baseline subtraction to remove and low frequency drifts in 
    the baseline.

    Parameters
    ----------
    config : traitlets.loader.Config
        Configuration specified by config file or cmdline arguments.
        Used to set traitlet values.
        Set to None if no configuration to pass.
    tool : ctapipe.core.Tool
        Tool executable that is calling this component.
        Passes the correct logger to the component.
        Set to None if no Tool to pass.

    """

    name = 'CHECMWaveformCleaner'

    window_width = Int(16, help='Define the width of the pulse '
                                'window').tag(config=True)
    window_shift = Int(8, help='Define the shift of the pulse window from the '
                               'peakpos (peakpos - shift).').tag(config=True)

    def __init__(self, config, tool, **kwargs):
        super().__init__(config=config, tool=tool, **kwargs)

        # Cleaning steps for plotting
        self.stages = {}
        self.stage_names = ['0: raw',
                            '1: baseline_sub',
                            '2: no_pulse',
                            '3: smooth_baseline',
                            '4: smooth_wf',
                            '5: cleaned']

        self.kernel = general_gaussian(10, p=1.0, sig=32)

        self.extractor = self.get_extractor()

    @abstractmethod
    def get_extractor(self):
        """
        Get the extractor to be used to define a window used to mask out the
        pulse.
        
        Returns
        -------
        `ChargeExtractor`

        """

    def apply(self, waveforms):
        samples = waveforms[0]

        # Subtract initial baseline
        baseline_sub = samples - np.mean(samples[:, :32], axis=1)[:, None]

        # Obtain waveform with pulse masked
        baseline_sub_b = baseline_sub[None, ...]
        window, _ = self.extractor.get_window_from_waveforms(waveforms)
        windowed = np.ma.array(baseline_sub_b, mask=window[0])
        no_pulse = np.ma.filled(windowed, 0)[0]

        # Get smooth baseline (no pulse)
        smooth_flat = np.convolve(no_pulse.ravel(), self.kernel, "same")
        smooth_baseline = np.reshape(smooth_flat, samples.shape)
        no_pulse_std = np.std(no_pulse, axis=1)
        smooth_baseline_std = np.std(smooth_baseline, axis=1)
        with np.errstate(divide='ignore', invalid='ignore'):
            smooth_baseline *= (no_pulse_std / smooth_baseline_std)[:, None]
            smooth_baseline[~np.isfinite(smooth_baseline)] = 0

        # Get smooth waveform
        smooth_wf = baseline_sub  # self.wf_smoother.apply(baseline_sub)

        # Subtract smooth baseline
        cleaned = smooth_wf - smooth_baseline

        self.stages['0: raw'] = samples
        self.stages['1: baseline_sub'] = baseline_sub
        self.stages['window'] = window
        self.stages['2: no_pulse'] = no_pulse
        self.stages['3: smooth_baseline'] = smooth_baseline
        self.stages['4: smooth_wf'] = smooth_wf
        self.stages['5: cleaned'] = cleaned

        return cleaned[None, :]


class CHECMWaveformCleanerAverage(CHECMWaveformCleaner):
    """
    Waveform cleaner used by CHEC-M.

    This cleaner performs 2 basline subtractions: a simple subtraction
    using the average of the first 32 samples in the waveforms, then a 
    convolved baseline subtraction to remove and low frequency drifts in 
    the baseline.
    
    This particular cleaner obtains the peak position using an 
    `AverageWfPeakIntegrator`.

    Parameters
    ----------
    config : traitlets.loader.Config
        Configuration specified by config file or cmdline arguments.
        Used to set traitlet values.
        Set to None if no configuration to pass.
    tool : ctapipe.core.Tool
        Tool executable that is calling this component.
        Passes the correct logger to the component.
        Set to None if no Tool to pass.
           
    """
    name = 'CHECMWaveformCleanerAverage'

    def get_extractor(self):
        return AverageWfPeakIntegrator(None, self.parent,
                                       window_width=self.window_width,
                                       window_shift=self.window_shift)


class CHECMWaveformCleanerLocal(CHECMWaveformCleaner):
    """
    Waveform cleaner used by CHEC-M.

    This cleaner performs 2 basline subtractions: a simple subtraction
    using the average of the first 32 samples in the waveforms, then a 
    convolved baseline subtraction to remove and low frequency drifts in 
    the baseline.

    This particular cleaner obtains the peak position using an 
    `LocalPeakIntegrator`.

    Parameters
    ----------
    config : traitlets.loader.Config
        Configuration specified by config file or cmdline arguments.
        Used to set traitlet values.
        Set to None if no configuration to pass.
    tool : ctapipe.core.Tool
        Tool executable that is calling this component.
        Passes the correct logger to the component.
        Set to None if no Tool to pass.

    """
    name = 'CHECMWaveformCleanerLocal'

    def get_extractor(self):
        return LocalPeakIntegrator(None, self.parent,
                                   window_width=self.window_width,
                                   window_shift=self.window_shift)


class WaveformCleanerFactory(Factory):
    """
    Factory to obtain a WaveformCleaner.
    """
    name = "WaveformCleanerFactory"
    description = "Obtain WavefromCleaner based on cleaner traitlet"

    subclasses = Factory.child_subclasses(WaveformCleaner)
    subclass_names = [c.__name__ for c in subclasses]

    cleaner = CaselessStrEnum(subclass_names, 'NullWaveformCleaner',
                              help='Waveform cleaning method to '
                                   'use.').tag(config=True)

    # Product classes traits
    window_width = Int(16, help='Define the width of the pulse '
                                'window').tag(config=True)
    window_shift = Int(8, help='Define the shift of the pulse window from the '
                               'peakpos (peakpos - shift).').tag(config=True)

    def get_factory_name(self):
        return self.name

    def get_product_name(self):
        return self.cleaner
