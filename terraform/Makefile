all: apply

include ../common.mk

config: $(patsubst %.template.py,%,$(wildcard *.tf.json.template.py))

init: check_branch config
	terraform init

validate: init
	terraform validate

plan: validate
	terraform plan

apply: validate
	$(MAKE) dereference_health_checks
	terraform apply
	$(MAKE) reference_health_checks
	$(MAKE) grafana

auto_apply: validate
	$(MAKE) dereference_health_checks
	terraform apply -auto-approve
	$(MAKE) reference_health_checks
	$(MAKE) grafana

grafana:
	python $(azul_home)/scripts/update_grafana.py

reference_health_checks:
	python $(azul_home)/scripts/provision_health_checks.py --reference

dereference_health_checks:
	python $(azul_home)/scripts/provision_health_checks.py --dereference

destroy: validate
	terraform destroy

auto_destroy: validate
	@echo '!!! All resources will be deleted in 10s, hit Ctrl-C to cancel !!!'; sleep 10
	terraform destroy -auto-approve

clean:
	rm -f *.tf.json

.PHONY: all config init validate plan apply auto_apply grafana reference_health_checks dereference_health_checks destroy auto_destroy clean
