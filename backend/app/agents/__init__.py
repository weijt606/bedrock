"""The dig crew.

    intake      any input          -> a Subject
    reader      Cala prose         -> structured layers, via GLiNER2
    prospector  a Subject          -> the ownership chain, hop by hop
    surveyor    a Subject          -> manufacturers, co-packers, shared factories
    statute     a Subject          -> the laws that govern what its label must say
    recorder    a Subject          -> litigation and sanctions listings, as filed
    enricher    a narrow question  -> Evidence carrying document URLs
    assay       raw Cala rows      -> entity kind, confidence, chain termination
    extractor   everything above   -> one CoreSample

Every agent that produces a user-visible claim must attach a Source. That is not
a convention, it is a required field on the schema, so an agent physically cannot
emit an unsourced fact.
"""
from .intake import IntakeAgent
from .prospector import ProspectorAgent
from .reader import ReaderAgent
from .surveyor import SurveyorAgent
from .statute import StatuteAgent
from .recorder import RecorderAgent
from .enricher import EnricherAgent
from .extractor import ExtractorAgent

__all__ = ["IntakeAgent", "ReaderAgent", "ProspectorAgent", "SurveyorAgent",
           "StatuteAgent", "RecorderAgent", "EnricherAgent", "ExtractorAgent"]
