import torch
import os

from pyfvvdp.utils import json2dict, PU
from pyfvvdp.video_source import *
from pyfvvdp.fvvdp_display_model import fvvdp_display_photometry, fvvdp_display_geometry

"""
PU21-PSNR metric. Usage is same as the FovVideoVDP metric (see pytorch_examples).
"""
class pu_psnr:
    def __init__(self, display_name="standard_4k", display_photometry=None, display_geometry=None, color_space="sRGB", quiet=False, device=None, display_models=None):
        self.color_space = color_space

        if display_photometry is None:
            self.display_photometry = fvvdp_display_photometry.load(display_name, models_file=display_models)
        else:
            self.display_photometry = display_photometry
        
        if display_geometry is None:
            self.display_geometry = fvvdp_display_geometry.load(display_name, models_file=display_models)
        else:
            self.display_geometry = display_geometry

        # Use GPU if available
        if device is None:
            if torch.cuda.is_available() and torch.cuda.device_count()>0:
                self.device = torch.device('cuda:0')
            else:
                self.device = torch.device('cpu')
        else:
            self.device = device

        self.load_config()
        self.pu = PU(self.display_photometry.get_black_level(), self.display_photometry.get_peak_luminance())


    def load_config( self ):
        parameters_file = os.path.join(os.path.dirname(__file__), "fvvdp_data/fvvdp_parameters.json")
        parameters = json2dict(parameters_file)

        self.shift = parameters['pu_psnr_shift']
        self.scale = parameters['pu_psnr_scale']

    '''
    Videos/images are encoded using perceptually uniform PU21 before computing PSNR.

    test_cont and reference_cont can be either numpy arrays or PyTorch tensors with images or video frames. 
        Depending on the display model (display_photometry), the pixel values should be either display encoded, or absolute linear.
        The two supported datatypes are float16 and uint8.
    dim_order - a string with the order of dimensions of test_cont and reference_cont. The individual characters denote
        B - batch
        C - colour channel
        F - frame
        H - height
        W - width
        Examples: "HW" - gray-scale image (column-major pixel order); "HWC" - colour image; "FCHW" - colour video
        The default order is "BCFHW". The processing can be a bit faster if data is provided in that order. 
    frame_padding - the metric requires at least 250ms of video for temporal processing. Because no previous frames exist in the
        first 250ms of video, the metric must pad those first frames. This options specifies the type of padding to use:
          'replicate' - replicate the first frame
          'circular'  - tile the video in the front, so that the last frame is used for frame 0.
          'pingpong'  - the video frames are mirrored so that frames -1, -2, ... correspond to frames 0, 1, ...
    '''
    def predict(self, test_cont, reference_cont, dim_order="BCFHW", frames_per_second=0, fixation_point=None, frame_padding="replicate"):

        test_vs = fvvdp_video_source_array( test_cont, reference_cont, frames_per_second, dim_order=dim_order, display_photometry=self.display_photometry, color_space_name=self.color_space )

        return self.predict_video_source(test_vs, fixation_point=fixation_point, frame_padding=frame_padding)

    '''
    The same as `predict` but takes as input fvvdp_video_source_* object instead of Numpy/Pytorch arrays.
    '''
    def predict_video_source(self, vid_source, fixation_point=None, frame_padding="replicate"):

        # T_vid and R_vid are the tensors of the size (1,1,N,H,W)
        # where:
        # N - the number of frames
        # H - height in pixels
        # W - width in pixels
        # Both images must contain linear absolute luminance values in cd/m^2
        # 
        # We assume the pytorch default NCDHW layout

        _, _, N_frames = vid_source.get_video_size()
        T = torch.stack([vid_source.get_test_frame(ff, device=self.device) for ff in range(N_frames)])
        R = torch.stack([vid_source.get_reference_frame(ff, device=self.device) for ff in range(N_frames)])

        # Apply PU
        T_enc = self.pu.encode(T)
        R_enc = self.pu.encode(R)

        psnr = self.psnr_fn(T_enc, R_enc)
        # we should not add that shift 
        #jod = psnr*self.scale + self.shift 
        return psnr, None

    def psnr_fn(self, img1, img2):
        mse = torch.mean( (img1 - img2)**2 )
        return 20*torch.log10( self.pu.peak/torch.sqrt(mse) )

    def short_name(self):
        return "PU21-PSNR"

    def quality_unit(self):
        return "dB"

    def get_info_string(self):
        return None