"""Import NCAP CA-FC 2026 scenarios as local scenarios: python -m pipeline import-ncap

The NCAP files in data/ncap/OpenSCENARIO/NCAP/CA-FC_2026/ are parametric base files; each
SingleExecution file is a ParameterValueDistribution that sets one concrete parameter point.
import_ncap() merges the two: loads the base file, applies the parameter overrides, then:
- adds an ObjectController/Controller element to the Ego ScenarioObject (required by write_scene());
- adds an ActivateControllerAction in the Ego Init Private block;
- appends a SimulationTimeCondition ConditionGroup to the StopTrigger (the existing stop
  conditions, which use VariableCondition, are preserved alongside the time limit);
- copies the xodr to target/<key>.xodr and sets LogicFile filepath to <key>.xodr;
- rewrites CatalogLocations Directory paths as paths relative to target/ so that
  write_scene() resolves them to the correct absolute paths at run time.
"""
import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from ..common import read_json, write_json

NCAP_DATA = Path(__file__).resolve().parent.parent.parent / 'data' / 'ncap' / 'OpenSCENARIO' / 'NCAP'
SINGLE = NCAP_DATA / 'CA-FC_2026' / 'Variations' / 'SingleExecution'

CONTROLLER = 'HiDriveController'
# mode=normal: HiDrive actively drives to setSpeed (injected per-scenario).
# TASC scenarios use mode=additive because their trajectory prescribes the speed;
# NCAP scenarios have no trajectory, so only normal mode produces a moving ego.
PROPERTIES = (('timeGap', '1.0'), ('mode', 'normal'), ('ADF_enabled', 'true'), ('Speed_limit', '100'))
STOP_TIME_S = '15.0'

# (key, title, group, single_execution_file)
# All ego objects are named 'Ego' in the NCAP CA-FC 2026 scenarios.
SCENARIOS = [
    ('ncap_ccrs_50',  'NCAP CCRs 50 kph',  'ncap_ccr',    'CCRs_50kph.xosc'),
    ('ncap_ccrb_50',  'NCAP CCRb 50 kph',  'ncap_ccr',    'CCRb_50kph.xosc'),
    ('ncap_ccrm_50',  'NCAP CCRm 50 kph',  'ncap_ccr',    'CCRm_50kph.xosc'),
    ('ncap_cbna_50',  'NCAP CBNA 50 kph',  'ncap_vru_cb', 'CBNA_50_50kph.xosc'),
    ('ncap_cbnao_50', 'NCAP CBNAO 50 kph', 'ncap_vru_cb', 'CBNAO_50_50kph.xosc'),
    ('ncap_cbfa_50',  'NCAP CBFA 50 kph',  'ncap_vru_cb', 'CBFA_50_50kph.xosc'),
    ('ncap_cbla_50',  'NCAP CBLA 50 kph',  'ncap_vru_cb', 'CBLA_50_50kph.xosc'),
]


def _resolve_base(xosc_path):
    """Return (root, base_dir): if xosc is a ParameterValueDistribution, load the base scenario
    and apply the parameter overrides; otherwise return the scenario as-is.

    base_dir is the directory the base scenario lives in (used to resolve relative xodr/catalog paths).
    """
    xosc_path = Path(xosc_path)
    tree = ET.parse(xosc_path)
    root = tree.getroot()

    pvd = root.find('ParameterValueDistribution')
    if pvd is None:
        return root, xosc_path.parent

    # Resolve the base scenario file
    base_rel = pvd.find('ScenarioFile').get('filepath')
    base_path = (xosc_path.parent / base_rel).resolve()
    base_tree = ET.parse(base_path)
    base_root = base_tree.getroot()

    # Collect parameter overrides from DeterministicSingleParameterDistribution
    overrides = {}
    for single in pvd.findall('.//DeterministicSingleParameterDistribution'):
        name = single.get('parameterName')
        elem = single.find('.//Element')
        if elem is not None:
            overrides[name] = elem.get('value')

    # Collect from DeterministicMultiParameterDistribution (take the first value set)
    for multi in pvd.findall('.//DeterministicMultiParameterDistribution'):
        for assignment in multi.findall('.//ParameterAssignment'):
            overrides[assignment.get('parameterRef')] = assignment.get('value')

    # Apply overrides to ParameterDeclarations
    for decl in base_root.findall('./ParameterDeclarations/ParameterDeclaration'):
        param_name = decl.get('name')
        if param_name in overrides:
            decl.set('value', overrides[param_name])

    return base_root, base_path.parent


def _add_controller(root, ego='Ego', ego_speed_kph=None):
    """Add ObjectController and ActivateControllerAction to the ego, same as tasc.py.

    ego_speed_kph: when provided, injects a setSpeed property (m/s) so HiDrive knows its
    cruise target.  NCAP scenarios have no trajectory, so without setSpeed HiDrive defaults
    to 0 m/s and the ego never moves.
    """
    item = root.find(f'./Entities/ScenarioObject[@name="{ego}"]')
    if item is None:
        raise ValueError(f'Ego entity {ego!r} not found in Entities.')
    if item.find('ObjectController') is None:
        controller = ET.SubElement(ET.SubElement(item, 'ObjectController'), 'Controller', name=CONTROLLER)
        properties = ET.SubElement(controller, 'Properties')
        for name, value in PROPERTIES:
            ET.SubElement(properties, 'Property', name=name, value=value)
        if ego_speed_kph is not None:
            ET.SubElement(properties, 'Property', name='setSpeed',
                          value=str(round(ego_speed_kph / 3.6, 4)))

    private = root.find(f'./Storyboard/Init/Actions/Private[@entityRef="{ego}"]')
    if private is None:
        return  # no Init Private for ego — unusual, skip
    if private.find('.//ActivateControllerAction') is None:
        holder = next(
            (action for action in private.findall('PrivateAction')
             if action.find('LongitudinalAction') is not None),
            None,
        )
        if holder is None:
            holder = ET.SubElement(private, 'PrivateAction')
        ET.SubElement(
            ET.SubElement(holder, 'ControllerAction'),
            'ActivateControllerAction', longitudinal='true', lateral='true',
        )


def _add_time_stop(root, value=STOP_TIME_S):
    """Append a SimulationTimeCondition ConditionGroup to StopTrigger without removing the existing
    conditions (VariableCondition, StandStill, etc.).  Returns True if one was added."""
    storyboard = root.find('Storyboard')
    stop = storyboard.find('StopTrigger')
    if stop is None:
        stop = ET.SubElement(storyboard, 'StopTrigger')
    if stop.find('.//SimulationTimeCondition[@rule="greaterThan"]') is not None:
        return False
    cg = ET.SubElement(stop, 'ConditionGroup')
    cond = ET.SubElement(cg, 'Condition', delay='0.0', conditionEdge='rising', name='SimTimeLimit')
    ET.SubElement(
        ET.SubElement(cond, 'ByValueCondition'),
        'SimulationTimeCondition', rule='greaterThan', value=value,
    )
    return True


def import_ncap(files=None, target=None):
    """Import NCAP scenarios into *target* (default: pipeline/scenarios/imported/).

    *files* is a list of (key, title, group, xosc_path) tuples.  When omitted the standard
    7 CA-FC 2026 single-execution scenarios are imported.
    """
    from . import LOCAL

    if target is None:
        target = LOCAL
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)

    if files is None:
        files = [(key, title, group, SINGLE / fname) for key, title, group, fname in SCENARIOS]

    registry_path = target / 'scenarios.json'
    registry = read_json(registry_path) if registry_path.is_file() else {}

    for key, title, group, xosc_path in files:
        xosc_path = Path(xosc_path)
        print(f'  importing {key} from {xosc_path.name} …', flush=True)

        root, base_dir = _resolve_base(xosc_path)

        ego = 'Ego'
        names = [obj.get('name') for obj in root.findall('./Entities/ScenarioObject')]
        if ego not in names:
            raise ValueError(f'{key}: ego {ego!r} not found; objects are {names}.')
        if len(names) < 2:
            raise ValueError(f'{key}: needs at least 2 objects, found {names}.')

        ego_speed_kph = None
        for decl in root.findall('./ParameterDeclarations/ParameterDeclaration'):
            if decl.get('name') == 'Ego_speed_kph':
                try:
                    ego_speed_kph = float(decl.get('value', '0'))
                except ValueError:
                    pass

        _add_controller(root, ego, ego_speed_kph=ego_speed_kph)
        _add_time_stop(root)

        # Fix xodr: resolve relative path, copy to target, update LogicFile
        logic = root.find('./RoadNetwork/LogicFile')
        xodr_abs = (base_dir / logic.get('filepath')).resolve()
        if not xodr_abs.is_file():
            raise FileNotFoundError(f'{key}: xodr not found at {xodr_abs}')
        shutil.copyfile(xodr_abs, target / f'{key}.xodr')
        logic.set('filepath', f'{key}.xodr')

        # Fix catalog paths: store relative paths from target so write_scene() resolves them
        for directory in root.findall('./CatalogLocations/*/Directory'):
            cat_abs = (base_dir / directory.get('path')).resolve()
            rel = os.path.relpath(cat_abs, target.resolve())
            directory.set('path', rel)

        # Write modified xosc
        ET.indent(root, space='  ')
        tree = ET.ElementTree(root)
        tree.write(target / f'{key}.xosc', encoding='utf-8', xml_declaration=True)

        registry[key] = {'title': title, 'file': f'{key}.xosc', 'group': group, 'ego': ego}

    write_json(registry_path, dict(sorted(registry.items())))
    print(f'{len(files)} NCAP scenario(s) imported into {target}.', flush=True)
