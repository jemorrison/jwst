#! /usr/bin/env python
from functools import partial

from ..stpipe import Step
from jwst.stpipe import record_step_status
from jwst import datamodels
from .pixel_replace import PixelReplacement
from functools import wraps
#from jwst.pipeline.calwebb_spec3 import invariant_filename

__all__ = ["PixelReplaceStep"]


class PixelReplaceStep(Step):
    """
    PixelReplaceStep: Module for replacing flagged bad pixels with an estimate
    of their flux, prior to spectral extraction.

    Attributes
    ----------
    algorithm : str
        Method used to estimate flux values for bad pixels. Currently only one option is
        implemented, using a profile fit to adjacent column values.

    n_adjacent_cols : int
        Number of adjacent columns (on either side of column containing a bad pixel) to use in
        creation of source profile, in cross-dispersion direction. The total number of columns
        used in the profile will be twice this number; on array edges, take adjacent columns until
        this number is reached.
    """

    class_alias = "pixel_replace"

    spec = """
        algorithm = option("fit_profile", "mingrad", "N/A", default="fit_profile")
        n_adjacent_cols = integer(default=3)    # Number of adjacent columns to use in creation of profile
        skip = boolean(default=True) # Step must be turned on by parameter reference or user
    """

    def process(self, input):
        """Execute the step.

        Parameters
        ----------
        input : JWST DataModel

        Returns
        -------
        JWST DataModel
            This will be `input` if the step was skipped; otherwise,
            it will be a model containing data arrays with estimated fluxes
            for any bad pixels, now flagged as TO-BE-DETERMINED (DQ bit 7?).
        """
        with datamodels.open(input) as input_model:
            # If more than one 2d spectrum exists in input, call replacement

            if isinstance(input_model, (datamodels.MultiSlitModel,
                                        datamodels.SlitModel,
                                        datamodels.ImageModel, 
                                        datamodels.IFUImageModel,
                                        datamodels.CubeModel)):
                self.log.debug(f'Input is a {input_model.meta.model_type}.')
            elif isinstance(input_model, datamodels.ModelContainer):
                self.log.debug('Input is a ModelContainer.')
            else:
                self.log.error(f'Input is of type {str(type(input_model))} for which')
                self.log.error('pixel_replace does not have an algorithm.')
                self.log.error('Pixel replacement will be skipped.')
                input_model.meta.cal_step.pixel_replace = 'SKIPPED'
                return input_model

            pars = {
                'algorithm': self.algorithm,
                'n_adjacent_cols': self.n_adjacent_cols,
            }

            # ___________________________________
            # calewbb_spec3 case / ModelContainer
            # __________________________________
            if isinstance(input_model, datamodels.ModelContainer):
                # Setup output path naming if associations are involved.
                # if input is ModelContainer do not copy the input_model
                # because assocation information is not copied.
                # Instead update input_modelin place. 
                asn_id = None
                try:
                    asn_id = input_model.asn_table["asn_id"]
                except (AttributeError, KeyError):
                    pass
                if asn_id is None:
                    asn_id = self.search_attr('asn_id')
                if asn_id is None: # it is still None. It does not exist. A ModelContainer was passed in with
                                   # no asn information
                    # to create the correct output name set the following.
                    self.output_use_model = True
                    self.save_model = invariant_filename(self.save_model)

                if asn_id is not None:
                    _make_output_path = self.search_attr(
                        '_make_output_path', parent_first=True
                    )
                    self._make_output_path = partial(
                        _make_output_path,
                        asn_id=asn_id
                    )

                # Check models to confirm they are the correct type
                for i, model in enumerate(input_model):
                    run_pixel_replace = True
                    if model.meta.model_type in ['MultiSlitModel', 'SlitModel',
                                                 'ImageModel', 'IFUImageModel', 'CubeModel']:
                        self.log.debug('Input is a {model.meta.model_type}.')
                    else:
                        self.log.error(f'Input is of type {model.meta.model_type} for which')
                        self.log.error('pixel_replace does not have an algorithm.')
                        self.log.error('Pixel replacement will be skipped.')
                        model.meta.cal_step.pixel_replace = 'SKIPPED'
                        run_pixel_replace = False

                    # all checks on model have passed. Now run pixel replacement
                    if run_pixel_replace:
                        replacement = PixelReplacement(model, **pars)
                        replacement.replace()
                        model = replacement.output
                        record_step_status(model, 'pixel_replace', success=True)
                return input_model
            # ________________________________________
            # calewbb_spec2 case - single input model
            # ________________________________________
            else:
                # Make copy of input to prevent overwriting
                result = input_model.copy()
                replacement = PixelReplacement(result, **pars)
                replacement.replace()
                record_step_status(replacement.output, 'pixel_replace', success=True)
                result = replacement.output
                return result
            

def invariant_filename(save_model_func):
    """Restore meta.filename after save_model"""

    @wraps(save_model_func)
    def save_model(model, **kwargs):
        try:
            filename = model.meta.filename
        except AttributeError:
            filename = None

        result = save_model_func(model, **kwargs)

        if filename:
            model.meta.filename = filename

        return result

    return save_model
