import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def catalog(): return json.loads((ROOT/'config/demos/production-demos.json').read_text())
def test_exactly_five_synthetic_one_click_scenarios():
 c=catalog(); assert c['synthetic'] is True; assert [x['id'] for x in c['scenarios']]==['release-risk','incident-rca','screenshot','architecture','recording']
def test_multimodal_demo_assets_exist_and_have_real_signatures():
 by={x['id']:x for x in catalog()['scenarios']}; png=(ROOT/by['screenshot']['asset']).read_bytes(); pdf=(ROOT/by['architecture']['asset']).read_bytes(); mp4=(ROOT/by['recording']['asset']).read_bytes(); assert png[:4]==b'\x89PNG'; assert pdf.startswith(b'%PDF-'); assert mp4[4:8]==b'ftyp'
def test_gateway_routes_demos_through_real_services_kafka_and_ingestion():
 t=(ROOT/'apps/gateway/src/demos/demos.service.ts').read_text(); assert 'ReleasesService' in t and 'InvestigationsService' in t and 'IngestionService' in t; assert '.createRiskAssessment(' in t and '.investigations.create(' in t and '.ingestion.accept(' in t
def test_live_ui_marks_every_demo_synthetic_and_calls_public_gateway_only():
 t=(ROOT/'apps/web/components/demos/production-demos.tsx').read_text(); assert 'SYNTHETIC DATA ONLY' in t and 'gatewayFetch' in t and '/api/v1/demos/' in t; assert '/internal/v1' not in t and ':8000' not in t
def test_no_manual_database_edit_path_is_present():
 for rel in ['apps/gateway/src/demos/demos.service.ts','apps/web/components/demos/production-demos.tsx']:
  t=(ROOT/rel).read_text().lower(); assert 'insert into' not in t and 'update ' not in t and 'psql ' not in t and 'manual database' not in t
