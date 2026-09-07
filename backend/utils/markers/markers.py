from __future__ import annotations
from .marker import CodeMarker, code_marker


class Markers:
    """Simplify operation registry. Each leaf's name() is the emitted metric name."""

    class CarePlan:
        @code_marker("care_plan.read_input")
        class ReadInput(CodeMarker): pass

        @code_marker("care_plan.find_medical_terms")
        class FindMedicalTerms(CodeMarker): pass

        @code_marker("care_plan.simplify_language")
        class SimplifyLanguage(CodeMarker): pass

        @code_marker("care_plan.clarify_actions")
        class ClarifyActions(CodeMarker): pass

        @code_marker("care_plan.structure_note")
        class StructureNote(CodeMarker): pass

        @code_marker("care_plan.save_output")
        class SaveOutput(CodeMarker): pass

        @code_marker("care_plan.pipeline")
        class Pipeline(CodeMarker): pass

    class Grading:
        @code_marker("grading.run")
        class Run(CodeMarker): pass

        @code_marker("grading.route")
        class Route(CodeMarker): pass

    class Http:
        @code_marker("http.request")
        class Request(CodeMarker): pass

    class Jobs:
        @code_marker("jobs.create_job")
        class CreateJob(CodeMarker): pass

        @code_marker("jobs.delete_job")
        class DeleteJob(CodeMarker): pass

    class Worker:
        @code_marker("worker.job_execute")
        class JobExecute(CodeMarker): pass

        @code_marker("worker.job_stage")
        class JobStage(CodeMarker): pass

    class Firestore:
        @code_marker("firestore.job_write")
        class JobWrite(CodeMarker): pass

    class Retention:
        @code_marker("retention.anon_user_cleanup")
        class AnonUserCleanup(CodeMarker): pass
