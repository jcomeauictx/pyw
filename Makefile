URL ?= file://$(PWD)/test.html
# `make V=` to use python2 instead
V ?= 3
IMPURE_PYTHON ?=
export
pyw: pyw.py
	python$(V) $< $(URL)
textmode:
	echo | $(MAKE) pyw
%.test: %.py
	python$(V) $<
%.pylint: %.py
	pylint$(V) $<
pylint: pyw.pylint parser.pylint
parser: parser.py
	python$(V) $< test.html
