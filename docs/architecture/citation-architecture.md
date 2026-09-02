# Citation Architecture

## Objective

Make every released Hallucination Protection claim traceable to stable, tenant-scoped evidence that a currently authorized user can preview. Citation identity is independent from presentation and is derived from tenant ID, document ID, chunk ID, source version, evidence SHA-256, and canonical locator JSON.

## Data model

`citations` is the immutable citation registry. `claim_citations` maps a Hallucination Protection `(verification_id, claim_id)` to one or more citations with the stored entailment score and whether the citation entails the released claim. Both tables are forced-RLS and append-only.

Citation locator variants are `text`, `page`, `timecode`, and `code`. Page locators may carry a bounding box. Timecode locators carry millisecond start/end positions. Code locators require a repository-relative path and validated line range.

## Claim closure

Citation creation starts from a tenant-scoped Hallucination Protection verification and its Self Corrective RAG source run. Only released claims are considered. Each mapped evidence chunk must exist in the source run, resolve to the same retrieval document, preserve the evidence SHA-256 used by Hallucination Protection, and meet the Hallucination Protection support threshold for that claim label. Bundle creation fails closed if any released claim lacks an entailing citation.

## Permission-safe preview

Knowing a citation ID is not authorization. Preview requires `retrieval.preview.read`, the citation source's `required_permission`, and current trusted service/environment/team/document-kind authorization. The SQL preview path re-applies these predicates before returning the cited chunk excerpt. Missing authorization returns no preview.

## UI boundary

The stable deep link is `/citations/{citation_id}`. Next.js calls only the public NestJS gateway. NestJS applies server-side retrieval permissions and calls the private FastAPI citation preview endpoint. Raw source/object-store URLs are not put in the deep link.
