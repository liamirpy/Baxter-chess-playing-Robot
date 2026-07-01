.PHONY: syntax clean

syntax:
	python3 -m py_compile $$(find controller ros scripts -name '*.py')

clean:
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
