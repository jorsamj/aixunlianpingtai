"""Small shared publication helpers. TaskRepository remains the pointer owner."""
from dataclasses import replace

from .payload_publications import PayloadPublicationIdentity, PayloadPublicationError, VERSION_REF


def preparation_input(store, task_id, project_id, kind, parent_id):
    data = ({'schema_version':2,'training_task_id':parent_id,'project_id':project_id}
            if kind=='TRAINING_PREPARE' else {'parent_task_id':parent_id})
    return store.prepare_payload_publication(PayloadPublicationIdentity(task_id=task_id, project_id=project_id,
        kind=kind, phase='create', expected_ref='', expected_parent_attempt=0,
        intent={'parent_task_id':parent_id}),data)


def ensure_preparation_input(context, parent):
    if VERSION_REF.fullmatch(context.task.payload_ref):
        return
    old=context.artifacts.read_json(context.task.task_id, context.task.payload_ref)
    key='training_task_id' if context.task.kind.value=='TRAINING_PREPARE' else 'parent_task_id'
    if not isinstance(old,dict) or old.get(key)!=parent.task_id or old.get('project_id',parent.project_id)!=parent.project_id:
        raise PermissionError('preparation input does not bind the parent')
    proposal=preparation_input(context.artifacts,context.task.task_id,parent.project_id,context.task.kind.value,parent.task_id)
    bound=context.repository.bind_preparation_input(context.lease,parent.task_id,proposal,context.artifacts)
    context.task=bound
    context.lease=replace(context.lease,task=bound)


def publication(store, task, phase, intent, payload, activation=None):
    identity=PayloadPublicationIdentity(task_id=task.task_id,project_id=task.project_id,kind=task.kind.value,
        phase=phase,expected_ref=task.payload_ref,expected_parent_attempt=task.attempt,intent=intent)
    try:
        return store.payload_reader.read_payload_publication_receipt(task.task_id,identity.operation_id,identity=identity)
    except PayloadPublicationError as error:
        if error.code!='PUBLICATION_RECEIPT_MISSING':
            raise
    return store.prepare_payload_publication(identity,payload,activation=activation)


def publish_training(context, parent, phase, payload):
    frozen = payload.get('input_freeze_ref')
    if not frozen:
        raise ValueError('TRAINING_FREEZE_REQUIRED: immutable frozen evidence required')
    if phase=='training.ready':
        match=VERSION_REF.fullmatch(parent.payload_ref)
        if not match:
            raise ValueError('TRAINING_FREEZE_REQUIRED: READY must follow committed freeze')
        prior=context.artifacts.payload_reader.read_payload_publication_receipt(parent.task_id,match['operation'])
        if prior.identity.data['phase']!='training.freeze':
            raise ValueError('TRAINING_FREEZE_REQUIRED: READY must follow committed freeze')
    activation=None
    if phase=='training.ready':
        activation={'resource_key':str(payload.get('target_resource_key') or
            ('training:remote:scheduler' if payload.get('target')=='remote' else 'training:auto')),
            'required_capabilities':list(payload.get('target_required_capabilities') or ('training.ultralytics',)), 'stage':'queued'}
    proposal=publication(context.artifacts,parent,phase,({'source_ref':parent.payload_ref} if phase=='training.freeze' else
        {'input_freeze_id':payload['input_freeze_id'],'snapshot_id':payload['snapshot_id'],
         'dataset_revision_id':payload['dataset_revision_id']}),payload,activation)
    return context.repository.publish_training_payload(parent.task_id,artifacts=context.artifacts,publication=proposal,
        child_task_id=context.task.task_id,child_lease_token=context.lease.lease_token,
        child_attempt=context.execution_generation,child_worker_id=context.lease.worker_id,child_payload_ref=context.task.payload_ref)
