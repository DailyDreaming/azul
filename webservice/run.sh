#!/bin/sh
echo "now substituting variables in Consonance config"

sed -i "s~___CONSONANCE_ADDRESS___~$CONSONANCE_ADDRESS~g" /root/.consonance/config
sed -i "s/___CONSONANCE_TOKEN___/$CONSONANCE_TOKEN/g" /root/.consonance/config
#sed -i "s/___awskey___/$AWS_ACCESS_KEY_ID/g" /etc/boto.cfg/credentials
#sed -i "s/___secretkey___/$AWS_SECRET_ACCESS_KEY/g" /etc/boto.cfg/credentials

echo "Substitution complete. File output:"
cat /root/.consonance/config

while ! pg_isready -U ${POSTGRES_USER} -h db
do
echo "$(date) - waiting for database to start"
    sleep 2
done

echo "Action Service Database Ready "

while ! pg_isready -U ${B_POSTGRES_USER} -h boardwalk-billing
do
echo "$(date) - waiting for database to start"
    sleep 2
done

echo "Billing Service Database Ready"

flask db upgrade
