"""Immutable execution provenance; current Task/lease authority stays in SQLite."""
from __future__ import annotations

from .task_runtime.payload_publications import VERSION_REF, EVIDENCE_REF


def _validate_documents(payload, documents):
    from .training_tasks import _training_input_freeze_digest
    from .snapshots import snapshot_content_matches_identity, dataset_revision_document
    frozen, snapshot, revision = (documents[key] for key in ('input_freeze_ref','snapshot_ref','dataset_revision_ref'))
    expected_revision = dataset_revision_document(snapshot)
    if (_training_input_freeze_digest(frozen) != payload.get('input_freeze_id')
            or frozen.get('snapshot_id') != payload.get('snapshot_id')
            or frozen.get('dataset_revision_id') != payload.get('dataset_revision_id')
            or not snapshot_content_matches_identity(snapshot,payload.get('snapshot_id'))
            or dataset_revision_document(snapshot).get('dataset_revision_id') != payload.get('dataset_revision_id')
            or revision.get('dataset_revision_id') != payload.get('dataset_revision_id')
            or any(revision.get(key) != value for key,value in expected_revision.items() if key != 'created_at')
            or frozen.get('history_admission') != payload.get('history_admission')):
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: frozen execution evidence mismatch')


def anchor_execution(context, payload):
    if not VERSION_REF.fullmatch(context.task.payload_ref):
        return None
    context.assert_current_execution()
    current=context.repository.get(context.task.task_id)
    if (current is None or current.status.value!='RUNNING' or current.attempt!=context.task.attempt
            or current.payload_ref!=context.task.payload_ref or current.worker_id!=context.lease.worker_id):
        raise PermissionError('execution input anchor requires the actual claimed generation')
    version=context.artifacts.payload_reader.read_payload_version(current.task_id,current.payload_ref)
    original=version.data
    if original != payload:
        raise ValueError('execution payload differs from its claimed immutable version')
    documents={}
    refs={}
    for key in ('input_freeze_ref','snapshot_ref','dataset_revision_ref'):
        ref=original.get(key)
        match=EVIDENCE_REF.fullmatch(str(ref))
        if match is None:
            raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: immutable execution evidence required')
        documents[key]=context.artifacts.read_json(current.task_id,ref)
        refs[key]={'ref':ref,'sha256':match['digest']}
    _validate_documents(original,documents)
    anchor={'protocol':'training-execution-input-v1','task_id':current.task_id,'project_id':current.project_id,
        'attempt':current.attempt,'payload_ref':current.payload_ref,'payload_sha256':version.digest,
        'snapshot_id':original['snapshot_id'],'dataset_revision_id':original['dataset_revision_id'],
        'input_freeze_id':original['input_freeze_id'],'evidence':refs,
        'history_admission':original.get('history_admission'),
        'algorithm_id':original.get('algorithm_asset_id') or original.get('asset_algorithm_id'),
        'base_version_id':original.get('base_version_id'),'base_model_sha256':original.get('base_model_sha256')}
    ref=context.artifacts.write_execution_anchor(current.task_id,current.attempt,anchor)
    context.assert_current_execution()
    return ref


def read_execution_inputs(artifacts, project_id, task_id, attempt, payload_ref, anchor_ref):
    expected=f'execution-inputs/v1/attempt-{attempt}.json'
    if type(attempt) is not int or attempt<1 or anchor_ref!=expected or not VERSION_REF.fullmatch(str(payload_ref)):
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: execution identity missing')
    anchor=artifacts.read_execution_anchor(task_id,attempt)
    version=artifacts.read_payload_version(task_id,payload_ref)
    payload=version.data
    if (anchor.get('protocol')!='training-execution-input-v1' or anchor.get('task_id')!=task_id
            or anchor.get('project_id')!=project_id or anchor.get('attempt')!=attempt
            or anchor.get('payload_ref')!=payload_ref or anchor.get('payload_sha256')!=version.digest
            or anchor.get('history_admission')!=payload.get('history_admission')
            or anchor.get('algorithm_id')!=(payload.get('algorithm_asset_id') or payload.get('asset_algorithm_id'))):
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: execution anchor binding mismatch')
    if any(anchor.get(key)!=payload.get(key) for key in ('base_version_id','base_model_sha256')):
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: original model version mismatch')
    documents={}
    for key in ('input_freeze_ref','snapshot_ref','dataset_revision_ref'):
        binding=(anchor.get('evidence') or {}).get(key) or {}
        match=EVIDENCE_REF.fullmatch(str(binding.get('ref')))
        if match is None or binding['ref']!=payload.get(key) or binding.get('sha256')!=match['digest']:
            raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: frozen evidence binding mismatch')
        documents[key]=artifacts.read_json(task_id,binding['ref'])
    _validate_documents(payload,documents)
    if any(anchor.get(key)!=payload.get(key) for key in ('snapshot_id','dataset_revision_id','input_freeze_id')):
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: execution evidence identity mismatch')
    return anchor,payload,documents
