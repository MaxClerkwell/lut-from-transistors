from collections import defaultdict
from skidl import Pin, Part, Alias, SchLib, SKIDL, TEMPLATE

from skidl.pin import pin_types

SKIDL_lib_version = '0.0.1'

generate = SchLib(tool=SKIDL).add_parts(*[
        Part(**{ 'name':'VDC', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'VDC'}), 'ref_prefix':'V', 'fplist':[''], 'footprint':'simulation:none', 'keywords':'simulation', 'description':'Voltage source, DC', 'datasheet':'https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml#sec_Independent_Sources_for', 'pins':[
            Pin(num='1',func=pin_types.PASSIVE,unit=1),
            Pin(num='2',func=pin_types.PASSIVE,unit=1)], 'unit_defs':[] }),
        Part(**{ 'name':'VPULSE', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'VPULSE'}), 'ref_prefix':'V', 'fplist':[''], 'footprint':'simulation:none', 'keywords':'simulation', 'description':'Voltage source, pulse', 'datasheet':'https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml#sec_Independent_Sources_for', 'pins':[
            Pin(num='1',func=pin_types.PASSIVE,unit=1),
            Pin(num='2',func=pin_types.PASSIVE,unit=1)], 'unit_defs':[] }),
        Part(**{ 'name':'PMOS_Substrate', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'PMOS_Substrate'}), 'ref_prefix':'Q', 'fplist':[''], 'footprint':'simulation:none', 'keywords':'mosfet pmos simulation', 'description':'P-channel MOSFET symbol with substrate (bulk) pin', 'datasheet':'https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml#cha_MOSFETs', 'pins':[
            Pin(num='1',name='D',func=pin_types.PASSIVE,unit=1),
            Pin(num='2',name='G',func=pin_types.INPUT,unit=1),
            Pin(num='3',name='S',func=pin_types.PASSIVE,unit=1),
            Pin(num='4',name='Bulk',func=pin_types.INPUT,unit=1)], 'unit_defs':[] }),
        Part(**{ 'name':'NMOS_Substrate', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'NMOS_Substrate'}), 'ref_prefix':'Q', 'fplist':[''], 'footprint':'simulation:none', 'keywords':'mosfet nmos simulation', 'description':'N-channel MOSFET symbol with substrate (bulk) pin', 'datasheet':'https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml#cha_MOSFETs', 'pins':[
            Pin(num='1',name='D',func=pin_types.PASSIVE,unit=1),
            Pin(num='2',name='G',func=pin_types.INPUT,unit=1),
            Pin(num='3',name='S',func=pin_types.PASSIVE,unit=1),
            Pin(num='4',name='Bulk',func=pin_types.INPUT,unit=1)], 'unit_defs':[] }),
        Part(**{ 'name':'C', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'C'}), 'ref_prefix':'C', 'fplist':[''], 'footprint':'simulation:none', 'keywords':'cap capacitor', 'description':'Unpolarized capacitor', 'datasheet':'', 'pins':[
            Pin(num='1',func=pin_types.PASSIVE,unit=1),
            Pin(num='2',func=pin_types.PASSIVE,unit=1)], 'unit_defs':[] })])